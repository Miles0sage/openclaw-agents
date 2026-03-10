#!/usr/bin/env python3
"""
Domain Information Tool - Comprehensive domain analysis
Retrieves DNS records (A, AAAA, MX, NS, TXT), WHOIS-like info (IP and reverse DNS),
and HTTP response headers from a domain
"""

import socket
import sys
import argparse
import logging
from typing import Dict, List, Tuple, Optional
import requests
from urllib.parse import urlparse

# Try to import dnspython, but make it optional
# dnspython is required for MX, NS, TXT record resolution
# If not available, the tool will gracefully skip those records
try:
    import dns.resolver
    DNS_AVAILABLE = True
except ImportError:
    DNS_AVAILABLE = False
    logger_msg = "Note: dnspython is not installed. For full DNS record resolution (MX, NS, TXT), install it with: pip install dnspython"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Request timeout
REQUEST_TIMEOUT = 5.0


def resolve_domain_a_record(domain: str) -> List[str]:
    """
    Resolve A records (IPv4) for a domain using socket.getaddrinfo
    
    Args:
        domain: Domain name to resolve
    
    Returns:
        List of IPv4 addresses
    """
    try:
        results = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
        ips = list(set([result[4][0] for result in results]))
        return sorted(ips)
    except socket.gaierror as e:
        logger.warning(f"Failed to resolve A records for {domain}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error resolving A records: {e}")
        return []


def resolve_domain_aaaa_record(domain: str) -> List[str]:
    """
    Resolve AAAA records (IPv6) for a domain using socket.getaddrinfo
    
    Args:
        domain: Domain name to resolve
    
    Returns:
        List of IPv6 addresses
    """
    try:
        results = socket.getaddrinfo(domain, None, socket.AF_INET6, socket.SOCK_STREAM)
        ips = list(set([result[4][0] for result in results]))
        return sorted(ips)
    except socket.gaierror:
        # IPv6 not available is normal on many systems
        return []
    except Exception as e:
        logger.warning(f"Unexpected error resolving AAAA records: {e}")
        return []


def resolve_dns_records_dnspython(domain: str) -> Dict[str, List[str]]:
    """
    Resolve DNS records (MX, NS, TXT) using dnspython library
    Falls back gracefully if dnspython is not available
    
    Args:
        domain: Domain name to resolve
    
    Returns:
        Dictionary with record types as keys and lists of records as values
    """
    records = {
        'MX': [],
        'NS': [],
        'TXT': []
    }
    
    if not DNS_AVAILABLE:
        logger.debug("dnspython not available, MX/NS/TXT records will not be retrieved")
        logger.info("Install dnspython for full DNS record resolution: pip install dnspython")
        return records
    
    try:
        # MX records
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            records['MX'] = sorted([str(rdata.exchange.to_text(True)).rstrip('.') 
                                   for rdata in mx_records])
            logger.debug(f"Successfully resolved {len(records['MX'])} MX records")
        except Exception as e:
            logger.debug(f"No MX records found or error resolving: {type(e).__name__}")
        
        # NS records
        try:
            ns_records = dns.resolver.resolve(domain, 'NS')
            records['NS'] = sorted([str(rdata.target.to_text(True)).rstrip('.') 
                                   for rdata in ns_records])
            logger.debug(f"Successfully resolved {len(records['NS'])} NS records")
        except Exception as e:
            logger.debug(f"No NS records found or error resolving: {type(e).__name__}")
        
        # TXT records
        try:
            txt_records = dns.resolver.resolve(domain, 'TXT')
            records['TXT'] = [str(rdata).strip('"') for rdata in txt_records]
            logger.debug(f"Successfully resolved {len(records['TXT'])} TXT records")
        except Exception as e:
            logger.debug(f"No TXT records found or error resolving: {type(e).__name__}")
            
    except Exception as e:
        logger.debug(f"General error during DNS record resolution: {e}")
        logger.warning("Some DNS records could not be retrieved due to resolver error")
    
    return records


def get_reverse_dns(ip: str) -> Optional[str]:
    """
    Perform reverse DNS lookup on an IP address
    
    Args:
        ip: IP address to look up
    
    Returns:
        Hostname if found, None otherwise
    """
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        return hostname
    except (socket.herror, socket.error) as e:
        logger.debug(f"Reverse DNS lookup failed for {ip}: {e}")
        return None


def get_http_headers(domain: str) -> Dict[str, str]:
    """
    Fetch HTTP response headers from a domain
    Tries both HTTP and HTTPS
    
    Args:
        domain: Domain name to fetch headers from
    
    Returns:
        Dictionary of HTTP headers
    """
    headers = {}
    
    # Try HTTPS first, then HTTP
    urls = [
        f"https://{domain}",
        f"http://{domain}"
    ]
    
    for url in urls:
        try:
            logger.info(f"Fetching headers from {url}...")
            response = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            headers = dict(response.headers)
            logger.info(f"Successfully fetched headers from {url}")
            return headers
        except requests.exceptions.Timeout:
            logger.debug(f"Timeout fetching {url}")
            continue
        except requests.exceptions.ConnectionError:
            logger.debug(f"Connection error for {url}")
            continue
        except requests.exceptions.RequestException as e:
            logger.debug(f"Request error for {url}: {e}")
            continue
        except Exception as e:
            logger.debug(f"Unexpected error fetching {url}: {e}")
            continue
    
    logger.warning(f"Could not fetch HTTP headers for {domain}")
    return {}


def format_report(domain: str, dns_data: Dict) -> str:
    """
    Format all collected data into a clean report
    
    Args:
        domain: The domain that was analyzed
        dns_data: Dictionary containing all collected DNS and HTTP data
    
    Returns:
        Formatted report string
    """
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append(f"Domain Information Report: {domain}")
    lines.append("=" * 80)
    
    # DNS Resolution Records
    lines.append("\n[DNS RESOLUTION RECORDS]")
    lines.append("-" * 80)
    
    if dns_data['A_records']:
        lines.append(f"A Records (IPv4):")
        for ip in dns_data['A_records']:
            lines.append(f"  • {ip}")
    else:
        lines.append("A Records (IPv4): None found")
    
    lines.append("")
    
    if dns_data['AAAA_records']:
        lines.append(f"AAAA Records (IPv6):")
        for ip in dns_data['AAAA_records']:
            lines.append(f"  • {ip}")
    else:
        lines.append("AAAA Records (IPv6): None found")
    
    lines.append("")
    
    if dns_data['MX_records']:
        lines.append(f"MX Records (Mail Servers):")
        for mx in dns_data['MX_records']:
            lines.append(f"  • {mx}")
    else:
        lines.append("MX Records (Mail Servers): None found")
    
    lines.append("")
    
    if dns_data['NS_records']:
        lines.append(f"NS Records (Name Servers):")
        for ns in dns_data['NS_records']:
            lines.append(f"  • {ns}")
    else:
        lines.append("NS Records (Name Servers): None found")
    
    lines.append("")
    
    if dns_data['TXT_records']:
        lines.append(f"TXT Records:")
        for txt in dns_data['TXT_records']:
            lines.append(f"  • {txt}")
    else:
        lines.append("TXT Records: None found")
    
    # WHOIS-like Information
    lines.append("\n[WHOIS-LIKE INFORMATION]")
    lines.append("-" * 80)
    
    if dns_data['primary_ip']:
        lines.append(f"Primary IP Address: {dns_data['primary_ip']}")
        
        # Reverse DNS for primary IP
        reverse_dns = dns_data['reverse_dns']
        if reverse_dns:
            lines.append(f"Reverse DNS: {reverse_dns}")
        else:
            lines.append("Reverse DNS: Not available")
    else:
        lines.append("Primary IP Address: Could not be determined")
        lines.append("Reverse DNS: Not available")
    
    # HTTP Response Headers
    lines.append("\n[HTTP RESPONSE HEADERS]")
    lines.append("-" * 80)
    
    if dns_data['http_headers']:
        for header, value in sorted(dns_data['http_headers'].items()):
            # Truncate very long header values
            if len(value) > 60:
                value = value[:57] + "..."
            lines.append(f"{header}: {value}")
    else:
        lines.append("No HTTP headers could be retrieved")
    
    lines.append("\n" + "=" * 80 + "\n")
    
    return "\n".join(lines)


def analyze_domain(domain: str) -> Dict:
    """
    Perform complete analysis of a domain
    
    Args:
        domain: Domain name to analyze
    
    Returns:
        Dictionary containing all collected information
    """
    logger.info(f"Starting analysis of domain: {domain}")
    
    # Resolve A records
    logger.info("Resolving A records...")
    a_records = resolve_domain_a_record(domain)
    
    # Resolve AAAA records
    logger.info("Resolving AAAA records...")
    aaaa_records = resolve_domain_aaaa_record(domain)
    
    # Resolve other DNS records with dnspython
    logger.info("Resolving MX, NS, and TXT records...")
    dns_records = resolve_dns_records_dnspython(domain)
    
    # Get primary IP for reverse DNS
    primary_ip = a_records[0] if a_records else (aaaa_records[0] if aaaa_records else None)
    reverse_dns = get_reverse_dns(primary_ip) if primary_ip else None
    
    # Get HTTP headers
    logger.info("Fetching HTTP headers...")
    http_headers = get_http_headers(domain)
    
    result = {
        'A_records': a_records,
        'AAAA_records': aaaa_records,
        'MX_records': dns_records['MX'],
        'NS_records': dns_records['NS'],
        'TXT_records': dns_records['TXT'],
        'primary_ip': primary_ip,
        'reverse_dns': reverse_dns,
        'http_headers': http_headers
    }
    
    logger.info("Domain analysis completed")
    return result


def main():
    """Main entry point for the domain info script"""
    parser = argparse.ArgumentParser(
        description='Get comprehensive information about a domain',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python3 domain_info.py example.com
  python3 domain_info.py google.com
  python3 domain_info.py github.com -v
        '''
    )
    
    parser.add_argument(
        'domain',
        help='Domain name to analyze'
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
        # Analyze the domain
        data = analyze_domain(args.domain)
        
        # Print formatted report
        report = format_report(args.domain, data)
        print(report)
        
        # Return 0 if we got at least some data
        if data['A_records'] or data['AAAA_records'] or data['http_headers']:
            return 0
        else:
            logger.warning(f"No information could be retrieved for {args.domain}")
            return 1
        
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\nError: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
