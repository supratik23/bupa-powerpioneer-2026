# Langgraph Agentic AI framework

This is FastAPI/ReactJS based application with exposed http endpoints to interact with agent.
It is using mainly Azure Cloud services setup like Azure OpenAI endpoints for LLM, Azure AI Search for vector database, Azure  Flexible server for MySQL for relational database. You can configure it with other cloud providers too if necessary.
It contains MCP servers and MCP clients in the same application. Few dummy MCP servers is there to start with the project initialization which is connected to MCP client. You can download the project and change the server logic according to your needs.
Apart from cloud based services for LLM, this framework also supports local LLM models running with Ollama.

### Future Improvements

```
  1. Add support for ChromaDB vector database and SQLite3 relational database.
  2. Add support for AWS setup with Amazon OpenSearch Service, Amazon Bedrock and Amazon RDS for MySQL
```



### StartUp command

```Linux/MacOS terminal
After activating virtual environment

pip3 install -r requirements.txt

uvicorn app.main:app --host 127.0.0.1  --port 8000 --reload OR ./startup_script.sh

``` 

### Http Urls

``` 
Swagger Docs - [Base-url]/docs

FastAPI - [Base-url]/

Agents - [Base-url]/agent/invoke

```

Invoke the agent with a `POST` request and a JSON body:

```bash
curl -X POST http://127.0.0.1:8000/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the capital of France?",
    "session_id": "test_session_123",
    "user_id": "test_user_456",
    "organization_id": "test_org_789",
    "organization_name": "Test Organization"
  }'
```

Opening `/agent/invoke` in a browser sends a `GET` request and does not invoke the agent. Use `POST` with all five fields above; otherwise FastAPI returns `422 Unprocessable Entity`.

### .env file setup - for local development
```
OPENAI_API_KEY= open ai api key
AZURE_OPENAI_ENDPOINT= Azure Foundry project url
AZURE_OPENAI_API_VERSION= Azure OpenAI deployment version
AZURE_OPENAI_DEPLOYMENT= Azure OpenAI deployment name
AZURE_OPENAI_MODEL= Azure openai model name

AZURE_SEARCH_SERVICE_NAME= Azure AI Search service
AZURE_SEARCH_API_KEY= Azure AI Search api key

# Ollama settings
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_SUPPORTS_TOOLS=true


DB_SERVER_NAME= Azure Db server name
DB_NAME= Azure DB name
DB_USERNAME= Azure DB username
DB_PASSKEY= Azure DB password
```


### Directory Structure

```
├── DigiCertGlobalRootCA.crt.pem - for Azure MySQL Flexible server DB interaction
├── README.md
├── app  -----------------------------------[main application folder for the whole application]
|--- frontend ----------------------- [Main react Frontend to call the fastapi]
|      |------ med-agent --------- [Chatbot to query the LLM agent]
│   ├── __init__.py
│   ├── main.py ----------------------------[entrypoint of the fastapi application]
│   ├── mcp_client  ------------------------[folder for configuring mcp clients]
│   │   ├── __init__.py
│   │   ├── agent.py  -----------------------[agent api and agent setting config file]
│   │   ├── graph.py  -----------------------[file for langgraph agent workflow]
│   │   ├── models.py   ---------------------[file for creating Pydantic Models and BaseModels]
│   │   └── serverconfig.py -----------------[configuration file for all mcp tools exposed for mcp clients]
│   ├── mcp_server --------------------------[folder for configuring mcp tools/functions and services]
│   │   ├── __init__.py
│   │   ├── ai_search_document_tool.py -------[azure AI Search mcp tool]
│   │   ├── create_material_tool.py  ---------[Create Material record in DB mcp tool] -Dummy
│   │   └── taskcreate_tool.py   -------------[Create Task record in DB mcp tool] -Dummy
│   └── services
│       ├── __init__.py
│       ├── azure_ai_search_service.py ---------[Azure AI Search service connection manager]
│       ├── db_service.py  ---------------------[Azure MySQL Flexible Server DB conn manager]
│       └── llm_service.py ---------------------[Azure OpenAI LLM connection manager service]
├── config.py ----------------------------------[config file env vars]
├── requirements.txt
├── tests -------------------------------------------[unit test cases folder]
```


## Agent workflow graph

```mermaid
flowchart TD
    START([START]) --> router["router"]

    router -.->|route_next: internal_agent_node| llm_agent["llm_agent_node"]
    router -.->|route_next: generic_agent_node| generic_agent["generic_agent_node"]

    llm_agent -.->|tools_condition: tool calls| tools["tools"]
    llm_agent -.->|tools_condition: no tool calls| END([END])
    llm_agent -->|direct edge| END

    tools --> llm_agent
    generic_agent --> END
```