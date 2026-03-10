#!/usr/bin/env python3
"""
Secure Password Generator Utility

Generates cryptographically secure random passwords with configurable character sets.
Uses Python's secrets module for cryptographic randomness suitable for security purposes.

Features:
- Configurable length (default: 16 characters)
- Optional uppercase letters (A-Z)
- Optional lowercase letters (a-z)
- Optional digits (0-9)
- Optional special characters (!@#$%^&*()_+-=[]{}|;:,.<>?)
- Ensures at least one character from each enabled character set
- CLI interface with examples and validation
"""

import argparse
import logging
import secrets
import string
import sys
from typing import List, Set


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Character sets
UPPERCASE = string.ascii_uppercase
LOWERCASE = string.ascii_lowercase
DIGITS = string.digits
SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?"

# Default configuration
DEFAULT_LENGTH = 16
DEFAULT_UPPERCASE = True
DEFAULT_LOWERCASE = True
DEFAULT_DIGITS = True
DEFAULT_SPECIAL = True


def build_character_set(
    include_uppercase: bool = True,
    include_lowercase: bool = True,
    include_digits: bool = True,
    include_special: bool = True
) -> str:
    """
    Build the character set based on configuration options.
    
    Args:
        include_uppercase: Include uppercase letters (A-Z)
        include_lowercase: Include lowercase letters (a-z)
        include_digits: Include digits (0-9)
        include_special: Include special characters
    
    Returns:
        String containing all allowed characters
        
    Raises:
        ValueError: If no character sets are enabled
    """
    charset = ""
    
    if include_uppercase:
        charset += UPPERCASE
    if include_lowercase:
        charset += LOWERCASE
    if include_digits:
        charset += DIGITS
    if include_special:
        charset += SPECIAL_CHARS
    
    if not charset:
        raise ValueError("At least one character set must be enabled")
    
    return charset


def ensure_character_requirements(
    password: str,
    length: int,
    include_uppercase: bool = True,
    include_lowercase: bool = True,
    include_digits: bool = True,
    include_special: bool = True
) -> str:
    """
    Ensure the password contains at least one character from each required set.
    If not, replace random characters to meet requirements.
    
    Args:
        password: The generated password
        length: Target password length
        include_uppercase: Require uppercase letters
        include_lowercase: Require lowercase letters
        include_digits: Require digits
        include_special: Require special characters
    
    Returns:
        Password guaranteed to meet all character requirements
    """
    password_list = list(password)
    required_chars = []
    
    # Collect required character types
    if include_uppercase and not any(c in UPPERCASE for c in password):
        required_chars.append(secrets.choice(UPPERCASE))
    if include_lowercase and not any(c in LOWERCASE for c in password):
        required_chars.append(secrets.choice(LOWERCASE))
    if include_digits and not any(c in DIGITS for c in password):
        required_chars.append(secrets.choice(DIGITS))
    if include_special and not any(c in SPECIAL_CHARS for c in password):
        required_chars.append(secrets.choice(SPECIAL_CHARS))
    
    # Replace random positions with required characters
    for required_char in required_chars:
        if len(required_chars) <= length:
            position = secrets.randbelow(length)
            password_list[position] = required_char
    
    return ''.join(password_list)


def generate_secure_password(
    length: int = DEFAULT_LENGTH,
    include_uppercase: bool = DEFAULT_UPPERCASE,
    include_lowercase: bool = DEFAULT_LOWERCASE,
    include_digits: bool = DEFAULT_DIGITS,
    include_special: bool = DEFAULT_SPECIAL
) -> str:
    """
    Generate a cryptographically secure random password.
    
    Args:
        length: Password length (minimum 4, maximum 128)
        include_uppercase: Include uppercase letters (A-Z)
        include_lowercase: Include lowercase letters (a-z)
        include_digits: Include digits (0-9)
        include_special: Include special characters
    
    Returns:
        Secure random password meeting all requirements
        
    Raises:
        ValueError: If length is invalid or no character sets enabled
    """
    if length < 4:
        raise ValueError("Password length must be at least 4 characters")
    if length > 128:
        raise ValueError("Password length must not exceed 128 characters")
    
    # Build character set
    charset = build_character_set(
        include_uppercase, include_lowercase, include_digits, include_special
    )
    
    # Generate random password
    password = ''.join(secrets.choice(charset) for _ in range(length))
    
    # Ensure character requirements are met
    password = ensure_character_requirements(
        password, length, include_uppercase, include_lowercase, 
        include_digits, include_special
    )
    
    return password


def generate_multiple_passwords(
    count: int,
    length: int = DEFAULT_LENGTH,
    include_uppercase: bool = DEFAULT_UPPERCASE,
    include_lowercase: bool = DEFAULT_LOWERCASE,
    include_digits: bool = DEFAULT_DIGITS,
    include_special: bool = DEFAULT_SPECIAL
) -> List[str]:
    """
    Generate multiple secure passwords with the same configuration.
    
    Args:
        count: Number of passwords to generate
        length: Password length
        include_uppercase: Include uppercase letters
        include_lowercase: Include lowercase letters
        include_digits: Include digits
        include_special: Include special characters
    
    Returns:
        List of secure passwords
        
    Raises:
        ValueError: If count is invalid or password parameters are invalid
    """
    if count < 1:
        raise ValueError("Count must be at least 1")
    if count > 100:
        raise ValueError("Count must not exceed 100")
    
    passwords = []
    for _ in range(count):
        password = generate_secure_password(
            length, include_uppercase, include_lowercase, include_digits, include_special
        )
        passwords.append(password)
    
    return passwords


def analyze_password_strength(password: str) -> dict:
    """
    Analyze password strength and composition.
    
    Args:
        password: Password to analyze
    
    Returns:
        Dictionary with strength analysis
    """
    analysis = {
        'length': len(password),
        'has_uppercase': any(c in UPPERCASE for c in password),
        'has_lowercase': any(c in LOWERCASE for c in password),
        'has_digits': any(c in DIGITS for c in password),
        'has_special': any(c in SPECIAL_CHARS for c in password),
        'unique_chars': len(set(password)),
        'character_sets_used': 0
    }
    
    # Count character sets used
    if analysis['has_uppercase']:
        analysis['character_sets_used'] += 1
    if analysis['has_lowercase']:
        analysis['character_sets_used'] += 1
    if analysis['has_digits']:
        analysis['character_sets_used'] += 1
    if analysis['has_special']:
        analysis['character_sets_used'] += 1
    
    # Calculate approximate entropy (bits)
    charset_size = 0
    if analysis['has_uppercase']:
        charset_size += len(UPPERCASE)
    if analysis['has_lowercase']:
        charset_size += len(LOWERCASE)
    if analysis['has_digits']:
        charset_size += len(DIGITS)
    if analysis['has_special']:
        charset_size += len(SPECIAL_CHARS)
    
    if charset_size > 0:
        import math
        analysis['entropy_bits'] = analysis['length'] * math.log2(charset_size)
    else:
        analysis['entropy_bits'] = 0
    
    return analysis


def format_password_output(
    passwords: List[str],
    show_analysis: bool = False,
    show_config: bool = False,
    config: dict = None
) -> str:
    """
    Format password output for display.
    
    Args:
        passwords: List of generated passwords
        show_analysis: Include strength analysis
        show_config: Include generation configuration
        config: Configuration used for generation
    
    Returns:
        Formatted output string
    """
    lines = []
    
    if show_config and config:
        lines.append("Password Generation Configuration:")
        lines.append(f"  Length: {config.get('length', 'N/A')}")
        lines.append(f"  Uppercase: {config.get('uppercase', 'N/A')}")
        lines.append(f"  Lowercase: {config.get('lowercase', 'N/A')}")
        lines.append(f"  Digits: {config.get('digits', 'N/A')}")
        lines.append(f"  Special: {config.get('special', 'N/A')}")
        lines.append("")
    
    if len(passwords) == 1:
        lines.append("Generated Password:")
        lines.append(f"  {passwords[0]}")
    else:
        lines.append(f"Generated {len(passwords)} Passwords:")
        for i, password in enumerate(passwords, 1):
            lines.append(f"  {i:2d}. {password}")
    
    if show_analysis and passwords:
        lines.append("")
        analysis = analyze_password_strength(passwords[0])
        lines.append("Password Strength Analysis:")
        lines.append(f"  Length: {analysis['length']} characters")
        lines.append(f"  Character sets used: {analysis['character_sets_used']}/4")
        lines.append(f"  Unique characters: {analysis['unique_chars']}")
        lines.append(f"  Estimated entropy: {analysis['entropy_bits']:.1f} bits")
        lines.append(f"  Has uppercase: {analysis['has_uppercase']}")
        lines.append(f"  Has lowercase: {analysis['has_lowercase']}")
        lines.append(f"  Has digits: {analysis['has_digits']}")
        lines.append(f"  Has special chars: {analysis['has_special']}")
    
    return "\n".join(lines)


def main():
    """Main entry point for the password generator script"""
    parser = argparse.ArgumentParser(
        description='Generate cryptographically secure random passwords',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python3 password_gen.py                    # Generate 16-char password with all character types
  python3 password_gen.py -l 32              # Generate 32-character password
  python3 password_gen.py -c 5               # Generate 5 passwords
  python3 password_gen.py --no-special       # Exclude special characters
  python3 password_gen.py --only-alnum       # Only letters and numbers
  python3 password_gen.py -l 12 -c 3 -a     # 3 passwords, 12 chars each, with analysis
        '''
    )
    
    parser.add_argument(
        '-l', '--length',
        type=int,
        default=DEFAULT_LENGTH,
        help=f'Password length (4-128, default: {DEFAULT_LENGTH})'
    )
    
    parser.add_argument(
        '-c', '--count',
        type=int,
        default=1,
        help='Number of passwords to generate (1-100, default: 1)'
    )
    
    parser.add_argument(
        '--no-uppercase',
        action='store_true',
        help='Exclude uppercase letters (A-Z)'
    )
    
    parser.add_argument(
        '--no-lowercase',
        action='store_true',
        help='Exclude lowercase letters (a-z)'
    )
    
    parser.add_argument(
        '--no-digits',
        action='store_true',
        help='Exclude digits (0-9)'
    )
    
    parser.add_argument(
        '--no-special',
        action='store_true',
        help='Exclude special characters'
    )
    
    parser.add_argument(
        '--only-alnum',
        action='store_true',
        help='Only alphanumeric characters (letters and digits)'
    )
    
    parser.add_argument(
        '-a', '--analysis',
        action='store_true',
        help='Show password strength analysis'
    )
    
    parser.add_argument(
        '--show-config',
        action='store_true',
        help='Show generation configuration'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    # Set logging level based on verbose flag
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    try:
        # Validate arguments
        if args.length < 4 or args.length > 128:
            print("Error: Password length must be between 4 and 128 characters")
            return 1
        
        if args.count < 1 or args.count > 100:
            print("Error: Count must be between 1 and 100")
            return 1
        
        # Determine character set configuration
        if args.only_alnum:
            include_uppercase = not args.no_uppercase
            include_lowercase = not args.no_lowercase
            include_digits = not args.no_digits
            include_special = False
        else:
            include_uppercase = not args.no_uppercase
            include_lowercase = not args.no_lowercase
            include_digits = not args.no_digits
            include_special = not args.no_special
        
        # Validate at least one character set is enabled
        if not any([include_uppercase, include_lowercase, include_digits, include_special]):
            print("Error: At least one character set must be enabled")
            return 1
        
        # Generate passwords
        logger.info(f"Generating {args.count} password(s) of length {args.length}")
        
        passwords = generate_multiple_passwords(
            count=args.count,
            length=args.length,
            include_uppercase=include_uppercase,
            include_lowercase=include_lowercase,
            include_digits=include_digits,
            include_special=include_special
        )
        
        # Format and display output
        config = {
            'length': args.length,
            'uppercase': include_uppercase,
            'lowercase': include_lowercase,
            'digits': include_digits,
            'special': include_special
        }
        
        output = format_password_output(
            passwords=passwords,
            show_analysis=args.analysis,
            show_config=args.show_config,
            config=config
        )
        
        print(output)
        
        logger.info("Password generation completed successfully")
        return 0
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\nPassword generation interrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())