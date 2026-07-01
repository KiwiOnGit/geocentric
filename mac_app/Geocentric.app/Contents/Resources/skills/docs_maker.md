# Technical Documentation & Instruction Drafting Skill

## Purpose
Use this skill when generating READMEs, API specifications, installation files, checklists, or instructions.

## 1. Core Directives
1. **Scannability & Structured Layout**: Use clear markdown headers, bold terms, code snippets, and list bullet points. Add warning/alert panels where critical setups are described.
2. **Step-by-Step Guidance**: Ensure setup scripts include exact pre-requisites, run environments, expected outputs, and troubleshooting FAQs.
3. **Task Tracking**: Maintain interactive task checklists using `<update_roadmap>` to keep the workspace aligned on long-term project progress.

## 2. Standardized Tech Docs Layout
A standard API or system documentation should follow this blueprint:
```markdown
# [Module Name / API Title]

## Overview
Brief non-technical description of the library's utility.

## Prerequisites & Installation
List of packages, node engines, and system dependencies.

## API Endpoints / Function Signatures
Clear syntax, input parameters, expected returns, and JSON payload blocks.

## Usage Guide & Code Examples
End-to-end operational code examples.

## Troubleshooting FAQ
Common error codes and recovery methods.
```

## 3. High-Quality Documentation Example

### Standardized Markdown README Output
```markdown
# Secure Token Manager API

## Overview
The Token Manager provides utility functions to securely generate, store, and validate authentication tokens inside a sandboxed SQLite environment.

## Prerequisites
* Python 3.10+
* `cryptography` library installed (`pip install cryptography`)

## Endpoints

### 1. Generate Token
Generates a cryptographically secure 256-bit token.

* **Path**: `/api/tokens/generate`
* **Method**: `POST`
* **Payload**:
```json
{
  "user_id": "usr_99f3",
  "expires_in_secs": 3600
}
```
* **Success Response (200)**:
```json
{
  "token": "a1b2c3d4...",
  "status": "active"
}
```

## Troubleshooting

### Error: `PermissionError` (Invalid directory boundary)
* **Reason**: User requested writing token logs outside the allocated sandbox.
* **Fix**: Ensure your relative output path resolves entirely within the workspace root.
```
