---
title: "RAG"
description: "Use document collections with embeddings and a vector store."
---

# RAG

RAG lets the agent search document collections and answer with context from uploaded material.

## Requirements

- A language model.
- An embeddings model.
- A vector store such as Qdrant.
- A collection with indexed documents.
- User permissions to read the collection.

## Troubleshooting

If search returns nothing, check that embeddings are selected for the user, Qdrant is reachable, documents are indexed, and the chat uses the expected collection.
