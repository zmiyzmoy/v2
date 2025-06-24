from fastapi import APIRouter, HTTPException, Body, Depends, Query
from typing import List, Optional
from uuid import uuid4
from datetime import datetime, timezone

from app.models.client_models import ClientConfiguration, hash_secret # Import the Beanie model and hash_secret
from app.schemas.admin_schemas import (
    ClientConfigurationCreateSchema,
    ClientConfigurationUpdateSchema,
    ClientConfigurationResponseSchema,
    PaginatedClientResponseSchema
)
from beanie.exceptions import RevisionIdWasChanged, DocumentNotFound
from beanie.odm.operators.update.general import Set

from app.core.security import verify_admin_credentials # ADDED: Import authentication dependency

router = APIRouter(
    dependencies=[Depends(verify_admin_credentials)] # ADDED: Apply auth to all routes in this router
)

# --- CRUD Endpoints ---

@router.post(
    "/clients",
    response_model=ClientConfigurationResponseSchema,
    status_code=201,
    summary="Create a new Client Configuration"
)
async def create_client_configuration(
    client_data: ClientConfigurationCreateSchema = Body(...)
):
    # Check if custom client_id is provided and if it already exists
    if client_data.client_id:
        existing_client = await ClientConfiguration.find_one(ClientConfiguration.client_id == client_data.client_id)
        if existing_client:
            raise HTTPException(status_code=409, detail=f"Client ID '{client_data.client_id}' already exists.")
    else:
        # Generate a unique client_id if not provided
        client_data.client_id = f"client_{uuid4().hex[:12]}"

    # Create the ClientConfiguration document instance
    client_doc_data = client_data.model_dump(exclude_none=True, exclude={"client_secret_plain"}) # Exclude plain secret from direct model data

    new_client = ClientConfiguration(**client_doc_data)

    # Hash secret if provided
    if client_data.client_secret_plain:
        new_client.set_secret(client_data.client_secret_plain)

    try:
        await new_client.insert()
    except Exception as e: # Catch potential DB errors, e.g., unique constraint violation if race condition
        raise HTTPException(status_code=500, detail=f"Failed to create client configuration: {e}")

    return await model_to_response(new_client)


@router.get(
    "/clients/{client_id}",
    response_model=ClientConfigurationResponseSchema,
    summary="Get a specific Client Configuration by Client ID"
)
async def get_client_configuration(client_id: str):
    client = await ClientConfiguration.find_one(ClientConfiguration.client_id == client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client configuration not found")
    return await model_to_response(client)


@router.get(
    "/clients",
    response_model=PaginatedClientResponseSchema,
    summary="List all Client Configurations with pagination"
)
async def list_client_configurations(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size")
):
    skip = (page - 1) * size
    total_clients = await ClientConfiguration.count()
    client_docs = await ClientConfiguration.find_all(skip=skip, limit=size).to_list()

    response_clients = [await model_to_response(client) for client in client_docs]

    return PaginatedClientResponseSchema(
        total=total_clients,
        page=page,
        size=size,
        results=response_clients
    )

@router.put(
    "/clients/{client_id}",
    response_model=ClientConfigurationResponseSchema,
    summary="Update a Client Configuration"
)
async def update_client_configuration(
    client_id: str,
    update_data: ClientConfigurationUpdateSchema = Body(...)
):
    client = await ClientConfiguration.find_one(ClientConfiguration.client_id == client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client configuration not found")

    update_payload = update_data.model_dump(exclude_none=True, exclude={"client_secret_plain"})

    set_operations = {}

    # Handle llm_config partial updates:
    # If llm_config is in the payload, merge its fields with the existing llm_config
    if "llm_config" in update_payload and update_payload["llm_config"] is not None:
        # Get current llm_config as dict
        current_llm_dict = client.llm_config.model_dump()
        # Get provided partial llm_config update as dict
        partial_llm_update_dict = update_payload["llm_config"] # This comes from LLMConfigSchema, so it's already a dict if parsed from request

        # Merge them
        merged_llm_dict = {**current_llm_dict, **partial_llm_update_dict}
        set_operations["llm_config"] = merged_llm_dict # Beanie's Set will handle the sub-document
        del update_payload["llm_config"] # Remove from main payload to avoid processing it again

    # Prepare update operations for other fields
    for key, value in update_payload.items(): # Use update_payload here
        set_operations[key] = value

    # Update client_secret_hashed if plain secret is provided
    if update_data.client_secret_plain:
        client.set_secret(update_data.client_secret_plain) # Hashes and sets client_secret_hashed on the model
        set_operations['client_secret_hashed'] = client.client_secret_hashed # Ensure this gets into $set

    # Always update the 'updated_at' timestamp
    set_operations['updated_at'] = datetime.now(timezone.utc)

    if not set_operations:
        raise HTTPException(status_code=400, detail="No update data provided")

    try:
        # Update the document in MongoDB using the $set operator
        await client.update(Set(set_operations))
        # The client instance in memory is not automatically updated by .update(),
        # so we re-fetch or update it manually for the response.
        # For simplicity, let's just use the fields we know changed or re-fetch.
        updated_client = await ClientConfiguration.find_one(ClientConfiguration.client_id == client_id)
        if not updated_client: # Should not happen if update was successful
             raise HTTPException(status_code=500, detail="Failed to retrieve client after update.")
        return await model_to_response(updated_client)
    except DocumentNotFound: # Should be caught by the initial find_one
        raise HTTPException(status_code=404, detail="Client configuration not found during update")
    except RevisionIdWasChanged:
        raise HTTPException(status_code=409, detail="Conflict: Document was updated by another process. Please retry.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update client configuration: {str(e)}")


@router.delete(
    "/clients/{client_id}",
    status_code=204, # No content
    summary="Delete a Client Configuration"
)
async def delete_client_configuration(client_id: str):
    client = await ClientConfiguration.find_one(ClientConfiguration.client_id == client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client configuration not found")

    try:
        await client.delete()
    except DocumentNotFound: # Should be caught by the initial find_one
        raise HTTPException(status_code=404, detail="Client configuration not found during delete")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete client configuration: {str(e)}")

    return None # Return None for 204 No Content
