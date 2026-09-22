# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 0.1.x   | ✅ |

We provide security fixes for the latest minor release line.

## Reporting a Vulnerability

**Do not open a public GitHub issue for a security vulnerability.**

Report vulnerabilities privately via **GitHub private vulnerability reporting**:

1. Navigate to the repository's **Security** tab
2. Click **Report a vulnerability**
3. Fill out the private advisory form

This ensures the report reaches the maintainers securely without public
disclosure.

Please include:
* a description of the issue and its impact
* steps to reproduce / a proof of concept
* affected versions
* any suggested remediation

## Scope

BlazeCrawl Core processes **arbitrary, attacker-controlled URLs**. We
especially want reports affecting:
* SSRF / DNS-rebinding / private-address bypass
* browser egress guard bypass
* redirect-based sandbox escape
* decompression / response-size bombs
* authentication bypass on the local key model
* injection via crafted HTML/sitemaps/robots.txt

Out of scope: denial of service by simply sending large volumes of legitimate
traffic to your own instance, and issues requiring already-authenticated
operator access.

## Response & Embargo

* We acknowledge reports within **3 business days**.
* We aim to provide a remediation or mitigation plan within **14 days**.
* We ask that you do not disclose publicly until a fix is released and a
  reasonable embargo (default 90 days) has elapsed.

## Security Model

See [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md).
