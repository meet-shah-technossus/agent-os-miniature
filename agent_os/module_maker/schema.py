"""Pydantic models for module definitions produced by the Module Maker."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiEndpoint(BaseModel):
    method: str = "GET"
    path: str = ""
    description: str = ""
    request_body: str = ""
    response_body: str = ""
    status_codes: list[str] = Field(default_factory=list)


class ClassSpec(BaseModel):
    name: str
    description: str = ""
    methods: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)


class FunctionSpec(BaseModel):
    name: str
    description: str = ""
    params: list[str] = Field(default_factory=list)
    returns: str = ""
    raises: list[str] = Field(default_factory=list)


class DbSchema(BaseModel):
    table_name: str
    columns: list[str] = Field(default_factory=list)
    description: str = ""
    indexes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class ModuleDefinition(BaseModel):
    """A single module as produced by the Module Maker agent."""
    module_id: str
    name: str
    feature_name: str = ""
    description: str = ""
    technical_spec: str = ""
    folder_structure: list[str] = Field(default_factory=list)
    apis: list[ApiEndpoint] = Field(default_factory=list)
    classes: list[ClassSpec] = Field(default_factory=list)
    functions: list[FunctionSpec] = Field(default_factory=list)
    db_schemas: list[DbSchema] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    testing_notes: str = ""
    constraints: list[str] = Field(default_factory=list)


class ModulePlan(BaseModel):
    """Complete output from the Module Maker: all modules for the project."""
    modules: list[ModuleDefinition] = Field(default_factory=list)
    project_folder_structure: list[str] = Field(default_factory=list)
