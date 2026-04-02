# Lumari Backend REST API Documentation

## Base URL

```
http://localhost:80/api/v1
```

## Authentication

All endpoints require Bearer token authentication using Supabase JWT.

### Getting an Access Token

```bash
curl -X POST "https://your-project.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: your-anon-key" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "your-password"
  }'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "..."
}
```

### Using the Token

Include the access token in the Authorization header for all requests:

```
Authorization: Bearer <access_token>
```

### Error Codes

| Code | Message | Description |
|------|---------|-------------|
| 401 | token_missing | No Authorization header provided |
| 401 | token_expired | JWT token has expired |
| 401 | token_invalid | JWT token is malformed or invalid |
| 403 | insufficient_permissions | User lacks required permissions |

## Endpoints

### Health Check

#### GET /health

Check API health status.

**Authentication:** Not required

**curl Example:**
```bash
curl -X GET "http://localhost:80/health"
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

---

## Transcripts

### Generate Report from Transcript

#### POST /transcripts/generate

Generate a structured report from a transcript using the multi-agent system.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "transcript": "string (min 50 chars, required)",
  "template_id": "uuid (optional)",
  "run_id": "uuid (optional)",
  "answers": {} (optional)
}
```

**Parameters:**
- `transcript`: The transcript text to process (minimum 50 characters)
- `template_id`: Optional UUID of a specific template to use
- `run_id`: Optional UUID to resume a previous run
- `answers`: Optional object with answers to previous questions (for HITL workflow)

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/transcripts/generate" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Baustellenbericht vom 14. Dezember 2025. Wetter: morgens bewölkt, mittags sonnig. Personal: 5 Mitarbeiter von Firma Müller Bau anwesend. Tätigkeiten: Betonarbeiten im Erdgeschoss fortgeführt, Schalung gestellt."
  }'
```

**Success Response (200):**
```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending_review",
  "report_content": "# Baustellenbericht\n\n## Datum\n14. Dezember 2025...",
  "report_format": "text",
  "title": "Baustellenbericht - 14.12.2025",
  "tags": ["Betonarbeiten", "Erdgeschoss"],
  "created_at": "2025-12-14T10:30:00Z",
  "template_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**HITL Response (200 with questions):**
```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "waiting_for_user",
  "questions": [
    {
      "id": "q1",
      "question": "Wie war die genaue Temperatur morgens?",
      "field_name": "weather_morning_temp",
      "kind": "text",
      "required": true
    },
    {
      "id": "q2",
      "question": "Welche Betongüte wurde verwendet?",
      "field_name": "concrete_grade",
      "kind": "text",
      "required": true
    }
  ],
  "run_id": "660e8400-e29b-41d4-a716-446655440001"
}
```

**Error Responses:**

400 Bad Request:
```json
{
  "detail": "Transcript must be at least 50 characters long"
}
```

401 Unauthorized:
```json
{
  "detail": "token_missing"
}
```

500 Internal Server Error:
```json
{
  "detail": "Error processing transcript: [error message]"
}
```

### Intake Transcript

#### POST /transcripts/intake

Alternative endpoint for transcript intake with simplified response.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "transcript": "string (required)",
  "template_id": "uuid (optional)"
}
```

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/transcripts/intake" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Kurzer Baustellenbericht mit grundlegenden Informationen..."
  }'
```

**Response (200):**
```json
{
  "intake_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "received"
}
```

---

## Templates

### Upload Template

#### POST /templates/upload

Upload a new report template.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

**Form Data:**
- `file`: Template file (JSON format)
- `name`: Template name (optional)
- `description`: Template description (optional)

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/templates/upload" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -F "file=@template.json" \
  -F "name=Baustellenbericht Standard" \
  -F "description=Standard template für Baustellenberichte"
```

**Template File Format (template.json):**
```json
{
  "name": "Baustellenbericht Standard",
  "version": "1.0",
  "fields": [
    {
      "name": "date",
      "type": "date",
      "required": true,
      "label": "Datum"
    },
    {
      "name": "weather",
      "type": "object",
      "required": true,
      "fields": [
        {
          "name": "morning",
          "type": "string",
          "label": "Wetter morgens"
        },
        {
          "name": "afternoon",
          "type": "string",
          "label": "Wetter mittags"
        }
      ]
    },
    {
      "name": "personnel",
      "type": "array",
      "required": true,
      "label": "Personal"
    }
  ]
}
```

**Response (200):**
```json
{
  "template_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Baustellenbericht Standard",
  "version": "1.0",
  "created_at": "2025-12-14T10:00:00Z",
  "status": "active"
}
```

**Error Responses:**

400 Bad Request:
```json
{
  "detail": "Invalid template format"
}
```

413 Payload Too Large:
```json
{
  "detail": "Template file too large (max 5MB)"
}
```

### List Templates

#### GET /templates

List all available templates for the authenticated user.

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters:**
- `limit`: Maximum number of results (default: 50, max: 100)
- `offset`: Pagination offset (default: 0)
- `search`: Search term for template name (optional)

**curl Example:**
```bash
curl -X GET "http://localhost:80/api/v1/templates?limit=10&offset=0" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response (200):**
```json
{
  "templates": [
    {
      "template_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "name": "Baustellenbericht Standard",
      "description": "Standard template für Baustellenberichte",
      "version": "1.0",
      "created_at": "2025-12-14T10:00:00Z",
      "updated_at": "2025-12-14T10:00:00Z",
      "status": "active"
    },
    {
      "template_id": "4fa85f64-5717-4562-b3fc-2c963f66afa7",
      "name": "Sicherheitsbericht",
      "description": "Template für Sicherheitsberichte",
      "version": "1.2",
      "created_at": "2025-12-10T08:00:00Z",
      "updated_at": "2025-12-12T15:30:00Z",
      "status": "active"
    }
  ],
  "total": 2,
  "limit": 10,
  "offset": 0
}
```

---

## Reports

### List Reports

#### GET /reports

List all reports for the authenticated user.

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters:**
- `limit`: Maximum number of results (default: 50, max: 100)
- `offset`: Pagination offset (default: 0)
- `status`: Filter by status: "draft", "pending_review", "confirmed" (optional)
- `from_date`: Filter reports from date (ISO 8601 format, optional)
- `to_date`: Filter reports to date (ISO 8601 format, optional)

**curl Example:**
```bash
curl -X GET "http://localhost:80/api/v1/reports?limit=20&status=confirmed" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response (200):**
```json
{
  "reports": [
    {
      "report_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Baustellenbericht - 14.12.2025",
      "status": "confirmed",
      "created_at": "2025-12-14T10:30:00Z",
      "updated_at": "2025-12-14T11:00:00Z",
      "tags": ["Betonarbeiten", "Erdgeschoss"],
      "template_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### Finalize Report

#### POST /reports/{report_id}/finalize

Finalize a draft report and sync it to the vector database.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Path Parameters:**
- `report_id`: UUID of the report to finalize

**Request Body:**
```json
{
  "final_edits": "string (optional)",
  "tags": ["string"] (optional)
}
```

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/reports/550e8400-e29b-41d4-a716-446655440000/finalize" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "tags": ["Betonarbeiten", "Erdgeschoss", "Fertiggestellt"]
  }'
```

**Response (200):**
```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "confirmed",
  "finalized_at": "2025-12-14T11:00:00Z",
  "synced_to_qdrant": true
}
```

**Error Responses:**

404 Not Found:
```json
{
  "detail": "Report not found"
}
```

409 Conflict:
```json
{
  "detail": "Report already finalized"
}
```

### Batch Upload Reports

#### POST /reports/batch

Upload multiple reports in batch.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "reports": [
    {
      "title": "string",
      "content": "string",
      "tags": ["string"],
      "template_id": "uuid (optional)"
    }
  ]
}
```

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/reports/batch" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "reports": [
      {
        "title": "Bericht 1",
        "content": "Inhalt von Bericht 1...",
        "tags": ["Tag1"]
      },
      {
        "title": "Bericht 2",
        "content": "Inhalt von Bericht 2...",
        "tags": ["Tag2"]
      }
    ]
  }'
```

**Response (200):**
```json
{
  "uploaded": 2,
  "failed": 0,
  "report_ids": [
    "660e8400-e29b-41d4-a716-446655440003",
    "770e8400-e29b-41d4-a716-446655440004"
  ]
}
```

### Delete Report

#### DELETE /reports/{report_id}

Delete a report.

**Headers:**
```
Authorization: Bearer <token>
```

**Path Parameters:**
- `report_id`: UUID of the report to delete

**curl Example:**
```bash
curl -X DELETE "http://localhost:80/api/v1/reports/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response (200):**
```json
{
  "deleted": true,
  "report_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Responses:**

404 Not Found:
```json
{
  "detail": "Report not found"
}
```

403 Forbidden:
```json
{
  "detail": "Cannot delete confirmed report"
}
```

---

## Assistant

### Check Questions

#### POST /assistant/check-questions

Check if the system has questions about a transcript (without generating a full report).

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "transcript": "string (required)",
  "template_id": "uuid (optional)"
}
```

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/assistant/check-questions" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Kurzer Baustellenbericht ohne Details..."
  }'
```

**Response (200):**
```json
{
  "has_questions": true,
  "questions": [
    {
      "id": "q1",
      "question": "Welches Datum hat der Bericht?",
      "field_name": "date",
      "kind": "text",
      "required": true
    },
    {
      "id": "q2",
      "question": "Wie war das Wetter?",
      "field_name": "weather",
      "kind": "text",
      "required": true
    }
  ]
}
```

### Ask Question

#### POST /assistant/ask

Ask a question to the assistant about reports or templates.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "question": "string (required)",
  "context": {
    "report_id": "uuid (optional)",
    "template_id": "uuid (optional)"
  }
}
```

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/assistant/ask" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Welche Berichte habe ich über Betonarbeiten?"
  }'
```

**Response (200):**
```json
{
  "answer": "Sie haben 3 Berichte über Betonarbeiten: ...",
  "sources": [
    {
      "report_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Baustellenbericht - 14.12.2025",
      "relevance": 0.95
    }
  ]
}
```

---

## Orchestration

### Resume Orchestration

#### POST /orchestration/resume

Resume a suspended orchestration with user answers (HITL workflow).

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "run_id": "uuid (required)",
  "answers": {
    "q1": "answer to question 1",
    "q2": "answer to question 2"
  }
}
```

**curl Example:**
```bash
curl -X POST "http://localhost:80/api/v1/orchestration/resume" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "660e8400-e29b-41d4-a716-446655440001",
    "answers": {
      "q1": "15 Grad Celsius",
      "q2": "C25/30"
    }
  }'
```

**Response (200):**
```json
{
  "status": "completed",
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "report_content": "# Baustellenbericht\n\n## Wetter\nMorgens: 15 Grad Celsius...",
  "report_format": "text"
}
```

**Alternative Response (200 - More Questions):**
```json
{
  "status": "waiting_for_user",
  "questions": [
    {
      "id": "q3",
      "question": "Weitere Frage...",
      "field_name": "additional_field",
      "kind": "text",
      "required": false
    }
  ],
  "run_id": "660e8400-e29b-41d4-a716-446655440001"
}
```

**Error Responses:**

404 Not Found:
```json
{
  "detail": "Run ID not found or expired"
}
```

400 Bad Request:
```json
{
  "detail": "Missing required answers for questions: q1, q2"
}
```

---

## Rate Limiting

The API implements rate limiting to prevent abuse:

- Anonymous requests: 10 requests/minute
- Authenticated requests: 100 requests/minute
- Template uploads: 10 uploads/hour
- Batch operations: 5 operations/minute

Rate limit headers are included in all responses:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1702558800
```

When rate limit is exceeded:

**Response (429):**
```json
{
  "detail": "Rate limit exceeded. Try again in 45 seconds."
}
```

---

## Error Handling

All errors follow a consistent format:

```json
{
  "detail": "Error message",
  "error_code": "ERROR_CODE (optional)",
  "timestamp": "2025-12-14T10:30:00Z"
}
```

### Common HTTP Status Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 200 | OK | Request successful |
| 400 | Bad Request | Invalid input, validation error |
| 401 | Unauthorized | Missing or invalid auth token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found |
| 409 | Conflict | Resource state conflict |
| 413 | Payload Too Large | Request body too large |
| 422 | Unprocessable Entity | Validation error |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server error |
| 503 | Service Unavailable | Service temporarily unavailable |

---

## Webhooks (Future)

Webhook support for real-time notifications is planned for a future release:

- `report.generated` - Fired when report generation completes
- `report.finalized` - Fired when report is finalized
- `orchestration.suspended` - Fired when HITL workflow requires user input

---

## Best Practices

### 1. Error Handling

Always check for error responses and handle them appropriately:

```bash
response=$(curl -s -w "\n%{http_code}" -X POST "..." ...)
http_code=$(echo "$response" | tail -n 1)
body=$(echo "$response" | head -n -1)

if [ "$http_code" -eq 200 ]; then
  echo "Success: $body"
else
  echo "Error ($http_code): $body"
fi
```

### 2. HITL Workflow

When generating reports, always check for the `waiting_for_user` status:

```bash
response=$(curl -X POST ".../transcripts/generate" ...)
status=$(echo "$response" | jq -r '.status')

if [ "$status" = "waiting_for_user" ]; then
  run_id=$(echo "$response" | jq -r '.run_id')
  questions=$(echo "$response" | jq '.questions')
  echo "Questions needed: $questions"
fi
```

### 3. Token Refresh

Tokens expire after 1 hour. Implement token refresh logic:

```bash
if [ "$http_code" -eq 401 ]; then
  curl -X POST "https://.../auth/v1/token?grant_type=refresh_token" \
    -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"
fi
```

### 4. Pagination

For large result sets, use pagination:

```bash
offset=0
limit=50

while true; do
  response=$(curl "http://.../reports?limit=$limit&offset=$offset" ...)
  total=$(echo "$response" | jq '.total')

  if [ $offset -ge $total ]; then
    break
  fi

  offset=$((offset + limit))
done
```

---

## Versioning

The API uses URI versioning. The current version is `v1`.

Future versions will be accessible via:
- `/api/v2/...`
- `/api/v3/...`

Version 1 will be maintained for at least 12 months after v2 release.

---

## Support

For API support and bug reports:
- GitHub Issues: [repository-url]/issues
- Email: support@lumari.example.com
- Documentation: [repository-url]/docs
