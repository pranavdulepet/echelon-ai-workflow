# Vercel Deployment Guide

This project is configured for deployment on Vercel.

## Prerequisites

1. A Vercel account
2. Environment variables configured in Vercel dashboard

## Environment Variables

Set the following environment variables in your Vercel project settings:

- `OPENAI_API_KEY` - Your OpenAI API key (required if using OpenAI)
- `ANTHROPIC_API_KEY` - Your Anthropic API key (required if using Claude)
- `LLM_PROVIDER` - Either "openai" or "anthropic" (default: "openai")
- `OPENAI_MODEL` - OpenAI model name (default: "gpt-5.1")
- `ANTHROPIC_MODEL` - Anthropic model name (default: "claude-3-5-sonnet-20241022")
- `SQLITE_PATH` - Path to SQLite database (default: "data/forms.sqlite")
- `MAX_CHANGED_ROWS` - Maximum rows that can be changed per request (default: 100)

## Deployment Steps

1. **Install Vercel CLI** (if deploying from command line):
   ```bash
   npm i -g vercel
   ```

2. **Deploy to Vercel**:
   ```bash
   vercel
   ```
   
   Or connect your GitHub repository to Vercel for automatic deployments.

3. **Configure Environment Variables**:
   - Go to your project settings in Vercel dashboard
   - Navigate to "Environment Variables"
   - Add all required variables listed above

## Project Structure

- `frontend/` - React frontend (built to `frontend/dist/`)
- `backend/` - FastAPI backend (wrapped in `api/index.py` for serverless)
- `api/` - Vercel serverless function handler
- `data/` - SQLite database (included in deployment)

## How It Works

- Frontend is built as a static site and served from `frontend/dist/`
- Backend API routes (`/api/*`) are handled by Python serverless functions
- The FastAPI app is wrapped with Mangum for AWS Lambda/Vercel compatibility
- Database path is automatically resolved relative to project root

## Important: Database File

The SQLite database file (`data/forms.sqlite`) is currently in `.gitignore`. For Vercel deployment, you have two options:

1. **Temporarily commit the database** (recommended for demo/deployment):
   - Remove `./data/forms.sqlite` from `.gitignore` temporarily
   - Commit and push the database file
   - Deploy to Vercel
   - Re-add it to `.gitignore` if needed

2. **Use Vercel's file upload** (if available in your plan):
   - Upload the database file through Vercel's dashboard or CLI

The database is read-only in the serverless environment, which is fine for this application.

## Notes

- The SQLite database is read-only in the serverless environment
- Cold starts may occur on first request after inactivity
- Consider using Vercel Pro for better performance and longer function execution times
- For production, consider using a managed database service instead of SQLite

