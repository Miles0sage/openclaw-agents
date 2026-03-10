
import re

def validate_email(email):
    # Regular expression for email validation
    # This regex handles:
    # 1. Standard email formats (e.g., user@example.com)
    # 2. Subdomains (e.g., user@sub.example.com)
    # 3. Plus addressing (e.g., user+tag@example.com)
    # 4. Hyphens in domain parts
    # 5. Numeric domains (e.g., user@123.com - though less common)
    # It does NOT handle:
    # - IP address domains (e.g., user@[192.168.1.1])
    # - Quoted strings in local part (e.g., "first last"@example.com)
    # - Internationalized domain names (IDNs)
    # - Top-level domains (TLDs) that are purely numeric (e.g., .123)

    # Regex breakdown:
    # ^                                  # Start of the string
    # (?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+    # Local part: one or more allowed characters
    # (?:\\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*) # Local part: allows for dot-separated segments
    # |                                  # OR
    # "(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f] # Quoted string local part (simplified, not fully RFC compliant)
    # | \\\\[\x01-\x09\x0b\x0c\x0e-\x7f])*") # Allows escaped characters in quoted string
    # )
    # @                                  # Separator
    # (?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+ # Domain part: one or more subdomain segments
    # [a-z0-9](?:[a-z0-9-]*[a-z0-9])?)    # Top-level domain (TLD)
    # $                                  # End of the string

    # A more practical and commonly used regex for general validation:
    email_regex = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    # This regex is a good balance for most common email validation needs.
    # It covers:
    # - Alphanumeric characters, periods, underscores, percent, plus, and hyphens in the local part.
    # - Plus addressing (e.g., user+tag@example.com).
    # - Subdomains (e.g., user@sub.domain.com).
    # - Alphanumeric characters, periods, and hyphens in the domain part.
    # - A top-level domain (TLD) of at least two alphabetic characters.

    if email_regex.match(email):
        return True
    else:
        return False

if __name__ == '__main__':
    # Test cases
    print(f"'test@example.com' is valid: {validate_email('test@example.com')}")
    print(f"'test.name@example.co.uk' is valid: {validate_email('test.name@example.co.uk')}")
    print(f"'test+tag@example.com' is valid: {validate_email('test+tag@example.com')}")
    print(f"'test@sub.example.com' is valid: {validate_email('test@sub.example.com')}")
    print(f"'test-name@example.com' is valid: {validate_email('test-name@example.com')}")
    print(f"'12345@example.com' is valid: {validate_email('12345@example.com')}")
    print(f"'test@example-domain.com' is valid: {validate_email('test@example-domain.com')}")
    print(f"'test@example.co' is valid: {validate_email('test@example.co')}") # Valid TLD with 2 chars

    print(f"'invalid-email' is valid: {validate_email('invalid-email')}")
    print(f"'test@.com' is valid: {validate_email('test@.com')}")
    print(f"'test@example' is valid: {validate_email('test@example')}")
    print(f"'@example.com' is valid: {validate_email('@example.com')}")
    print(f"'test@example..com' is valid: {validate_email('test@example..com')}")
    print(f"'test@example.c' is valid: {validate_email('test@example.c')}") # Invalid TLD with 1 char
    print(f"'' is valid: {validate_email('')}")
    print(f"'test@example_domain.com' is valid: {validate_email('test@example_domain.com')}") # Underscore in domain is generally invalid
