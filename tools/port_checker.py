#!/usr/bin/env python3
"""
Port Checker Tool - Scans common ports on a domain
Checks the top 20 common ports and reports their status
"""

import socket
import sys
import argparse
import logging
from typing import Dict, Tuple, List
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Top 20 common ports to check
COMMON_PORTS = {
    80: "HTTP",
    443: "HTTPS",
    22: "SSH",
    21: "FTP",
    25: "SMTP",
    8080: "HTTP-ALT",
    8443: "HTTPS-ALT",
    3306: "MySQL",
    5432: "PostgreSQL",
    27017: "MongoDB",
    6379: "Redis",
    9200: "Elasticsearch",
    11211: "Memcached",
    53: "DNS",
    110: "POP3",
    143: "IMAP",
    993: "IMAPS",
    995: "POP3S",
    587: "SMTP-TLS",
    465: "SMTPS"
}

SOCKET_TIMEOUT = 3.0  # 3 second timeout per port


def check_port(host: str, port: int) -> Tuple[str, str]:
    """
    Check if a port is open, closed, or filtered
    
    Args:
        host: Target hostname or IP address
        port: Port number to check
    
    Returns:
        Tuple of (status, symbol) where status is 'OPEN', 'CLOSED', or 'FILTERED'
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            return "OPEN", "✓"
        else:
            return "CLOSED", "✗"
            
    except socket.timeout:
        return "FILTERED", "⊗"
    except socket.gaierror:
        return "ERROR", "!"
    except socket.error:
        return "FILTERED", "⊗"
    except Exception as e:
        logger.warning(f"Unexpected error checking port {port}: {e}")
        return "ERROR", "!"


def resolve_domain(domain: str) -> str:
    """
    Resolve domain name to IP address
    
    Args:
        domain: Domain name to resolve
    
    Returns:
        IP address string
        
    Raises:
        socket.gaierror: If domain cannot be resolved
    """
    try:
        ip = socket.gethostbyname(domain)
        return ip
    except socket.gaierror as e:
        logger.error(f"Failed to resolve domain '{domain}': {e}")
        raise


def format_table(domain: str, results: Dict[int, Tuple[str, str]]) -> str:
    """
    Format the port check results as a formatted table
    
    Args:
        domain: The target domain that was scanned
        results: Dictionary mapping port number to (status, symbol) tuple
    
    Returns:
        Formatted table string
    """
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append(f"Port Scan Results for: {domain}")
    lines.append("=" * 80)
    lines.append(f"{'Port':<8} {'Service':<20} {'Status':<12} {'Symbol':<8}")
    lines.append("-" * 80)
    
    # Sort by port number
    for port in sorted(results.keys()):
        status, symbol = results[port]
        service = COMMON_PORTS.get(port, "Unknown")
        lines.append(f"{port:<8} {service:<20} {status:<12} {symbol:<8}")
    
    lines.append("=" * 80)
    
    # Summary statistics
    open_count = sum(1 for status, _ in results.values() if status == "OPEN")
    closed_count = sum(1 for status, _ in results.values() if status == "CLOSED")
    filtered_count = sum(1 for status, _ in results.values() if status == "FILTERED")
    error_count = sum(1 for status, _ in results.values() if status == "ERROR")
    
    lines.append(f"\nSummary:")
    lines.append(f"  Open:     {open_count}")
    lines.append(f"  Closed:   {closed_count}")
    lines.append(f"  Filtered: {filtered_count}")
    lines.append(f"  Error:    {error_count}")
    lines.append(f"  Total:    {len(results)}")
    lines.append("=" * 80 + "\n")
    
    return "\n".join(lines)


def scan_ports(domain: str) -> Dict[int, Tuple[str, str]]:
    """
    Scan all common ports on the target domain
    
    Args:
        domain: Target domain or IP address
    
    Returns:
        Dictionary mapping port numbers to (status, symbol) tuples
    """
    results = {}
    
    logger.info(f"Starting port scan on {domain}...")
    logger.info(f"Scanning {len(COMMON_PORTS)} common ports...")
    
    for port in sorted(COMMON_PORTS.keys()):
        logger.info(f"Checking port {port}/{COMMON_PORTS[port]}...")
        status, symbol = check_port(domain, port)
        results[port] = (status, symbol)
        time.sleep(0.1)  # Small delay between checks to avoid overwhelming the network
    
    logger.info("Port scan completed.")
    return results


def main():
    """Main entry point for the port checker script"""
    parser = argparse.ArgumentParser(
        description='Check common ports on a domain',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python3 port_checker.py scanme.nmap.org
  python3 port_checker.py google.com
  python3 port_checker.py 192.168.1.1
        '''
    )
    
    parser.add_argument(
        'domain',
        help='Domain name or IP address to scan'
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
        # Resolve domain to IP
        logger.info(f"Resolving domain: {args.domain}")
        ip = resolve_domain(args.domain)
        logger.info(f"Resolved to IP: {ip}")
        
        # Scan ports
        results = scan_ports(args.domain)
        
        # Print formatted results
        table = format_table(args.domain, results)
        print(table)
        
        return 0
        
    except socket.gaierror:
        print(f"\nError: Unable to resolve domain '{args.domain}'")
        print("Please check the domain name and try again.")
        return 1
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\nError: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
