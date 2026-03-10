#!/usr/bin/env python3
"""
HTTP Headers Fetcher Tool

Fetches and displays HTTP response headers from a given URL.
Supports both formatted table output and JSON output.

Usage:
    python3 http_headers.py <URL> [--json]
    python3 http_headers.py https://example.com
    python3 http_headers.py https://example.com --json
"""

import sys
import argparse
import logging
import json
import urllib.request
import urllib.error
from collections import OrderedDict


def format_table_output(status_code, headers_dict):
    """
    Format headers as a clean table output.
    
    Args:
        status_code (int): HTTP status code
        headers_dict (dict): Dictionary of headers
    
    Returns:
        str: Formatted table output
    """
    lines = []
    lines.append("=" * 70)
    lines.append("HTTP Response Headers".center(70))
    lines.append("=" * 70)
    lines.append("")
    
    # Status line
    lines.append(f"Status Code: {status_code}")
    lines.append("-" * 70)
    lines.append("")
    
    # Headers section
    if headers_dict:
        lines.append("Headers:")
        lines.append("-" * 70)
        
        # Sort headers for consistent output
        for header_name in sorted(headers_dict.keys()):
            header_value = headers_dict[header_name]
            # Format: "Header-Name: value"
            lines.append(f"{header_name}: {header_value}")
        
        lines.append("-" * 70)
    else:
        lines.append("No headers found")
        lines.append("-" * 70)
    
    lines.append("")
    return "\n".join(lines)


def fetch_headers(url, verbose=False):
    """
    Fetch HTTP headers from the given URL.
    
    Args:
        url (str): URL to fetch headers from
        verbose (bool): Enable verbose logging
    
    Returns:
        tuple: (status_code, headers_dict) or None on error
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    logger = logging.getLogger(__name__)
    
    # Ensure URL has scheme
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        logger.debug(f"Added https:// scheme to URL: {url}")
    
    logger.debug(f"Fetching headers from: {url}")
    
    try:
        # Create request with a User-Agent to avoid some blocking
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Python-HTTP-Headers-Tool/1.0'}
        )
        
        # Make the request
        with urllib.request.urlopen(req) as response:
            status_code = response.status
            
            # Get headers - convert to dict for consistent access
            headers_dict = OrderedDict()
            for header_name, header_value in response.headers.items():
                headers_dict[header_name] = header_value
            
            logger.debug(f"Successfully fetched {len(headers_dict)} headers")
            return status_code, headers_dict
            
    except urllib.error.HTTPError as e:
        # HTTPError has a code and headers
        status_code = e.code
        headers_dict = OrderedDict()
        for header_name, header_value in e.headers.items():
            headers_dict[header_name] = header_value
        
        logger.debug(f"HTTP Error {status_code}: {e.reason}")
        return status_code, headers_dict
        
    except urllib.error.URLError as e:
        logger.error(f"URL Error: {e.reason}")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching headers: {e}")
        return None


def generate_json_output(status_code, headers_dict, url):
    """
    Generate JSON output with status code and headers.
    
    Args:
        status_code (int): HTTP status code
        headers_dict (dict): Dictionary of response headers
        url (str): The URL that was requested
    
    Returns:
        str: JSON formatted string
    """
    # Extract key headers for easy access
    content_type = headers_dict.get('Content-Type', 'Not specified')
    server = headers_dict.get('Server', 'Not specified')
    content_length = headers_dict.get('Content-Length', 'Not specified')
    
    # Build the output structure
    output_data = {
        'url': url,
        'status_code': status_code,
        'summary': {
            'content_type': content_type,
            'server': server,
            'content_length': content_length
        },
        'headers': dict(headers_dict)
    }
    
    return json.dumps(output_data, indent=2)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Fetch and display HTTP response headers from a URL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 http_headers.py https://example.com
  python3 http_headers.py https://example.com --json
  python3 http_headers.py example.com -v
  python3 http_headers.py https://example.com --json -v
        """
    )
    
    parser.add_argument(
        'url',
        help='URL to fetch headers from'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output headers as JSON'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Fetch headers
    result = fetch_headers(args.url, verbose=args.verbose)
    
    if result is None:
        return 1
    
    status_code, headers_dict = result
    
    # Output based on format flag
    if args.json:
        # Output as JSON with enhanced structure
        json_output = generate_json_output(status_code, headers_dict, args.url)
        print(json_output)
    else:
        # Output as formatted table
        print(format_table_output(status_code, headers_dict))
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
