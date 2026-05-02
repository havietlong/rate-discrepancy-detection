import re
import json
from pathlib import Path

class RateParser:
    def __init__(self, patterns_file="rate_patterns.json"):
        """Load rate detection patterns from JSON file"""
        with open(patterns_file, 'r') as f:
            self.config = json.load(f)
        
        self.patterns = self.config['patterns']
        self.skip_keywords = self.config['skip_keywords']
        self.rate_cleaning = self.config['rate_cleaning']
    
    def clean_rate(self, rate_str, original_text=""):
        """
        Clean and convert rate string to float
        Handles commas AND dots as thousand separators
        """
        # Remove both commas and dots (they are thousand separators)
        # But careful: dot could be decimal in some cases (not in VND)
        rate_str = rate_str.replace(',', '')
        rate_str = rate_str.replace('.', '')  # Remove dot thousand separators
        
        try:
            rate = float(rate_str)
        except:
            return None
        
        # Fix missing zero (e.g., "2,100,00" -> 2100000)
        if self.rate_cleaning['fix_missing_zeros']:
            if rate < 1000000 and rate > 100000 and 'nett' in original_text.lower():
                rate = rate * 10
            if rate < 100000 and rate > 10000:
                rate = rate * 100
        
        # Validate against min/max
        if rate < self.rate_cleaning['minimum_rate']:
            return None
        if rate > self.rate_cleaning['maximum_rate']:
            return None
        
        return rate
    
    def detect_pp_rate(self, text):
        """
        Detect ++ rates (e.g., 'VND 2.050.000++' or '2,050,000++')
        """
        for pattern in self.patterns['pp_rates']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                rate_str = match.group(1)
                rate = self.clean_rate(rate_str, text)
                if rate:
                    return rate, "++ rate detected"
        return None, None
    
    def detect_monthly(self, text):
        """Check if this is a monthly rate (should be skipped)"""
        for pattern in self.patterns['monthly']:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def detect_nett_rate(self, text):
        """Detect NETT rates (e.g., 'VND2,100,000 NETT')"""
        for pattern in self.patterns['nett_rates']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                rate_str = match.group(1)
                rate = self.clean_rate(rate_str, text)
                if rate:
                    return rate, "NETT rate detected"
        return None, None
    
    def detect_date_specific_rate(self, text, target_date):
        """
        Detect date-specific rates with date ranges
        Returns: (rate, rate_source, date_range_start, date_range_end)
        """
        from datetime import datetime
        
        for pattern in self.patterns['date_specific']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            
            for match in matches:
                rate_str = match[0]
                start_str = match[1]
                end_str = match[2]
                
                try:
                    start_date = datetime.strptime(start_str, '%d-%b-%y')
                    end_date = datetime.strptime(end_str, '%d-%b-%y')
                    
                    if start_date <= target_date <= end_date:
                        rate = self.clean_rate(rate_str)
                        if rate:
                            return rate, f"Date-specific: {start_str} to {end_str}", start_date, end_date
                except:
                    continue
        
        return None, None, None, None
    
    def detect_flat_rate(self, text):
        """Detect flat rates (no date range)"""
        for pattern in self.patterns['flat_rates']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # match could be a string or tuple depending on pattern
                rate_str = match if isinstance(match, str) else match[0]
                rate = self.clean_rate(rate_str, text)
                if rate:
                    return rate, "Flat rate detected"
        return None, None
    
    def has_rate_adjustment(self, text):
        """Check if comment mentions any rate adjustment/balance"""
        for keyword in self.patterns['rate_adjustments']:
            if re.search(keyword, text, re.IGNORECASE):
                return True
        return False
    
    def parse_rates(self, comment_text, target_date):
        """
        Main function to parse rates from comment text
        """
        # Skip if contains monthly indicators
        if self.detect_monthly(comment_text):
            return None, "Monthly rate - skipped (assumed correct)", {'monthly': True, 'skip': True}
        
        # Check for rate adjustments FIRST
        has_adjustment = self.has_rate_adjustment(comment_text)
        
        # Priority 1: Date-specific rates
        rate, source, start, end = self.detect_date_specific_rate(comment_text, target_date)
        if rate:
            if has_adjustment:
                source = f"{source} (with rate adjustment)"
            return rate, source, {'date_range': {'start': start, 'end': end}, 'has_adjustment': has_adjustment}
        
        # Priority 2: NETT rates
        rate, source = self.detect_nett_rate(comment_text)
        if rate:
            if has_adjustment:
                source = f"{source} (with rate adjustment)"
            return rate, source, {'type': 'nett', 'has_adjustment': has_adjustment}
        
        # Priority 3: ++ rates
        rate, source = self.detect_pp_rate(comment_text)
        if rate:
            if has_adjustment:
                source = f"{source} (with rate adjustment)"
            return rate, source, {'type': 'pp', 'has_adjustment': has_adjustment}
        
        # Priority 4: Flat rates
        rate, source = self.detect_flat_rate(comment_text)
        if rate:
            if has_adjustment:
                source = f"{source} (with rate adjustment)"
            return rate, source, {'type': 'flat', 'has_adjustment': has_adjustment}
        
        # No rate found
        return None, "No rate found", {'has_adjustment': has_adjustment}
    
    def get_skip_reason(self, text):
        """Check if comment should be skipped (deposits, discounts, etc.)"""
        for keyword in self.skip_keywords:
            if re.search(keyword, text, re.IGNORECASE):
                return f"Skipped: contains '{keyword}'"
        return None