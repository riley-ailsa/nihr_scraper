# Docker Deployment Guide

Complete guide for deploying the NIHR scraper using Docker and Docker Compose.

## Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit .env with your API keys
nano .env

# 3. Build and run (one-time execution)
docker-compose up nihr-scraper

# 4. Or run with cron (scheduled execution)
docker-compose up -d nihr-scraper-cron
```

## Deployment Modes

### Mode 1: One-Time Execution

Run the scraper once and exit:

```bash
docker-compose up nihr-scraper
```

Use cases:
- Manual scraping
- Testing
- Ad-hoc data updates

### Mode 2: Scheduled Execution (Cron)

Run the scraper on a schedule:

```bash
docker-compose up -d nihr-scraper-cron
```

Default schedule: Daily at 2:00 AM (configurable via `CRON_SCHEDULE`)

Use cases:
- Production deployment
- Automated monitoring
- Continuous data sync

### Mode 3: Standalone (No Database)

Use external PostgreSQL and Pinecone:

```bash
# Build image
docker build -t nihr-scraper .

# Run with external services
docker run --rm \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/nihr_urls.txt:/app/nihr_urls.txt \
  nihr-scraper
```

## Configuration

### Environment Variables

Required in `.env`:

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Pinecone
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=ailsa-grants

# PostgreSQL
DATABASE_URL=postgresql://user:password@host:port/database
```

For docker-compose with bundled PostgreSQL:

```bash
# Set postgres password
POSTGRES_PASSWORD=your_secure_password

# DATABASE_URL is auto-configured in docker-compose.yml
```

### Cron Schedule

Set `CRON_SCHEDULE` in docker-compose.yml or as environment variable:

```yaml
environment:
  CRON_SCHEDULE: "0 2 * * *"  # Daily at 2 AM
```

Examples:
- `0 */6 * * *` - Every 6 hours
- `0 2 * * 0` - Sundays at 2 AM
- `30 14 * * 1-5` - Weekdays at 2:30 PM

### Volume Mounts

Persist data and configuration:

```yaml
volumes:
  - ./logs:/app/logs              # Log files
  - ./nihr_urls.txt:/app/nihr_urls.txt  # URL tracking
```

## Docker Compose Services

### postgres

Bundled PostgreSQL database (optional):

```yaml
postgres:
  image: postgres:16-alpine
  ports:
    - "5432:5432"
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./init.sql:/docker-entrypoint-initdb.d/init.sql
```

Skip this service if using external database.

### nihr-scraper

One-time execution:

```yaml
nihr-scraper:
  build: .
  command: python3 ingest_nihr.py
  restart: "no"
```

### nihr-scraper-cron

Scheduled execution:

```yaml
nihr-scraper-cron:
  build: .
  command: ./docker-entrypoint.sh cron
  restart: unless-stopped
```

## Building

### Build Image

```bash
docker build -t nihr-scraper .
```

### Build with Docker Compose

```bash
docker-compose build
```

### Build Arguments

None currently, but can add for customization:

```dockerfile
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim
```

## Running

### One-Time Run

```bash
# Using docker-compose
docker-compose up nihr-scraper

# Using docker directly
docker run --rm --env-file .env nihr-scraper
```

### Scheduled Run (Background)

```bash
# Start cron service
docker-compose up -d nihr-scraper-cron

# View logs
docker-compose logs -f nihr-scraper-cron

# Stop service
docker-compose down nihr-scraper-cron
```

### Test Mode

```bash
docker run --rm --env-file .env nihr-scraper ./docker-entrypoint.sh test
```

### Dry Run Mode

```bash
docker run --rm --env-file .env nihr-scraper ./docker-entrypoint.sh dry-run
```

## Monitoring

### View Logs

```bash
# Docker compose logs
docker-compose logs -f nihr-scraper-cron

# Container logs
docker logs -f nihr-scraper-cron

# File logs (via volume mount)
tail -f logs/scraper_*.log
tail -f logs/cron.log
```

### Check Status

```bash
# Container status
docker-compose ps

# Health check
docker inspect nihr-scraper-cron | grep Health

# Database connection
docker-compose exec postgres psql -U postgres -d ailsa -c "SELECT COUNT(*) FROM grants WHERE source = 'nihr';"
```

### Execute Commands in Container

```bash
# Interactive shell
docker-compose exec nihr-scraper-cron /bin/bash

# Run scraper manually
docker-compose exec nihr-scraper-cron python3 ingest_nihr.py

# Check crontab
docker-compose exec nihr-scraper-cron crontab -l
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs nihr-scraper-cron

# Verify environment
docker-compose config

# Test build
docker-compose build --no-cache
```

### Database Connection Issues

```bash
# Check postgres is running
docker-compose ps postgres

# Test connection from scraper
docker-compose exec nihr-scraper-cron psql $DATABASE_URL -c "SELECT 1;"

# Check database logs
docker-compose logs postgres
```

### Cron Not Running

```bash
# Verify cron is active
docker-compose exec nihr-scraper-cron ps aux | grep cron

# Check crontab
docker-compose exec nihr-scraper-cron crontab -l

# View cron logs
docker-compose exec nihr-scraper-cron cat /app/logs/cron.log
```

### Permission Issues

```bash
# Fix log directory permissions
chmod 777 logs/

# Or rebuild with proper permissions
docker-compose build --no-cache
```

### Python Import Errors

```bash
# Verify Python path
docker-compose exec nihr-scraper-cron python3 -c "import sys; print(sys.path)"

# Test imports
docker-compose exec nihr-scraper-cron python3 -c "from src.ingest.nihr_funding import NihrFundingScraper; print('OK')"
```

## Production Deployment

### Recommended Setup

```yaml
version: '3.8'

services:
  nihr-scraper-cron:
    build: .
    container_name: nihr-scraper-prod
    restart: unless-stopped
    env_file: .env
    environment:
      CRON_SCHEDULE: "0 2 * * *"
    volumes:
      - ./logs:/app/logs:rw
      - ./nihr_urls.txt:/app/nihr_urls.txt:ro
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "python3", "-c", "from src.ingest.nihr_funding import NihrFundingScraper"]
      interval: 60s
      timeout: 10s
      retries: 3
```

### Security Hardening

```dockerfile
# Run as non-root user (already implemented)
USER scraper

# Use specific Python version
FROM python:3.11.8-slim

# Pin dependency versions
RUN pip install --no-cache-dir -r requirements.txt --require-hashes
```

### Resource Limits

```yaml
services:
  nihr-scraper-cron:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### Logging

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
    labels: "service=nihr-scraper"
```

### Auto-Restart

```yaml
restart: unless-stopped
```

## Maintenance

### Update Image

```bash
# Pull latest code
git pull

# Rebuild image
docker-compose build

# Restart service
docker-compose up -d nihr-scraper-cron
```

### Backup Database

```bash
# Dump database
docker-compose exec postgres pg_dump -U postgres ailsa > backup.sql

# Or use volume backup
docker run --rm \
  -v nihr_postgres_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/postgres_backup.tar.gz /data
```

### Clean Up

```bash
# Remove stopped containers
docker-compose rm

# Remove unused images
docker image prune

# Remove volumes (CAUTION: deletes data)
docker-compose down -v
```

### View Disk Usage

```bash
docker system df
```

## Multi-Environment Setup

### Development

```yaml
# docker-compose.dev.yml
services:
  nihr-scraper:
    build:
      context: .
      target: development
    command: ./docker-entrypoint.sh dry-run
    volumes:
      - .:/app  # Live code reload
```

### Staging

```yaml
# docker-compose.staging.yml
services:
  nihr-scraper-cron:
    environment:
      CRON_SCHEDULE: "0 */6 * * *"  # More frequent for testing
```

### Production

```yaml
# docker-compose.prod.yml
services:
  nihr-scraper-cron:
    restart: always
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://logs.example.com:514"
```

Run with:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Build and Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build image
        run: docker build -t nihr-scraper .

      - name: Run tests
        run: docker run --rm nihr-scraper ./docker-entrypoint.sh test

      - name: Deploy
        run: |
          docker save nihr-scraper | gzip > nihr-scraper.tar.gz
          scp nihr-scraper.tar.gz user@server:/opt/
          ssh user@server "docker load < /opt/nihr-scraper.tar.gz && docker-compose up -d"
```

## Performance Optimization

### Layer Caching

```dockerfile
# Copy requirements first (cached if unchanged)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy code last (changes frequently)
COPY . .
```

### Multi-Stage Build

```dockerfile
# Build stage
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
COPY . /app
```

### Image Size

Current image: ~200MB

Reduce with:
- Alpine base image
- Multi-stage builds
- Remove development dependencies

## Support

For issues:
1. Check container logs: `docker-compose logs`
2. Verify environment: `docker-compose config`
3. Test locally: `docker-compose up nihr-scraper`
4. Review file logs: `logs/scraper_*.log`
