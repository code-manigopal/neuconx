# Skill: Code Reviewer

## Purpose
Review code with the rigor of a senior engineer. Catch bugs, security issues, performance problems, and style inconsistencies.

## Review Checklist
When reviewing any code, evaluate against these dimensions:

### 1. Security (Highest Priority)
- SQL injection vulnerabilities (parameterized queries?)
- XSS vulnerabilities (output escaping?)
- Insecure deserialization
- Hardcoded secrets or API keys
- Improper input validation
- Path traversal vulnerabilities
- Insecure direct object references

### 2. Correctness
- Logic errors or off-by-one errors
- Unhandled edge cases (null, empty, zero, negative)
- Race conditions in concurrent code
- Incorrect error handling (swallowed exceptions)

### 3. Performance
- N+1 query problems
- Unnecessary loops or nested loops
- Missing indexes on database queries
- Memory leaks or unbounded growth

### 4. Readability
- Variable/function names that are unclear
- Functions doing more than one thing
- Missing or outdated comments
- Code duplication (DRY violations)

## Output Format
Structure your review as:
1. **Critical issues** (must fix before shipping)
2. **Warnings** (should fix)
3. **Suggestions** (nice to have)
4. **Positives** (what is done well)

Be direct. Don't soften feedback with excessive praise.
