# {module_name} — Implementation Prompt

## Role
You are an expert {language} software engineer.

## Instructions
Implement the **{module_name}** module for the **{project_name}** project exactly as specified.

## Situation
{description}

{technical_spec}

### Dependencies
This module depends on: {dependencies}

## Expected Output
Produce working, production-quality code for the following:

### API Endpoints
{api_section}

### Classes
{class_section}

### Functions
{function_section}

### Database Schemas
{db_section}

### File Paths
{file_paths_section}

## Norms
- Follow the project's existing patterns and conventions.
- Include tests alongside implementation.
- Do NOT add files or endpoints beyond what is specified.
- Write a `summary.md` when done, ending with "END".

{review_section}
