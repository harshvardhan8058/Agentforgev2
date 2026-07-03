# Requirements Document

## Introduction

This spec covers **Phase 3 (Agentic Layer)** of the AgentForge platform. Phases 1
(Foundation) and 2 (Core RAG) are already built and provide the reusable, pluggable
seams this phase builds on: an async FastAPI `API_Service` with a uniform error
envelope and typed schemas, a pluggable `LLM_Provider` (Groq primary, deterministic
keyless Fallback default), a pluggable `Embedding_Provider` and `Vector_Store`
(Chroma local / pgvector production), a `RAG_Service` that produces grounded answers
with citations, and Postgres + pgvector and Redis infrastructure. All credentials
remain optional and the system must stay fully runnable and testable with no external
credentials.

Phase 3 adds an **agent** that reasons in a bounded loop, calls tools (including the
existing RAG pipeline and an optional web search), maintains short-term and long-term
memory, persists multi-turn conversations, streams incremental output to clients, and
records lightweight traces of each step. The agentic layer MUST reuse — not
reimplement — the existing pluggable seams, and MUST be structured so new tools and new
agent node types can be added without modifying the agent core, setting up the later
multi-agent phase.

Explicitly OUT OF SCOPE for this spec (reserved for later phases): multi-agent
collaboration (planner/researcher/writer/critic), human-approval workflows, enterprise
authentication/RBAC/multi-tenancy, cost dashboards/token analytics/prompt
versioning/evaluation frameworks, the React frontend, third-party integrations
(Slack/Gmail/Drive/GitHub/crawling/scheduled agents), and cloud deployment. The
architecture MUST remain modular so those later phases can be added without rework.

## Glossary

- **Agentic_Layer**: The Phase 3 subsystem delivered by this spec, composed of the
  Agent_Orchestrator, Tool_Registry, Tools, Memory_Manager, Conversation_Store,
  Streaming_Service, and Trace_Recorder.
- **Agent_Orchestrator**: The component that runs the bounded reasoning loop as a
  stateful graph of nodes (reason, act/tool-call, observe) until a final answer is
  produced or a bound is reached. Implemented on LangGraph.
- **Agent_Run**: A single invocation of the Agent_Orchestrator for one user request
  within a Conversation, from the first reasoning step to a final answer or terminal
  bound.
- **Agent_Step**: One node execution within an Agent_Run (a reasoning step, a tool
  call, or an observation).
- **Iteration_Limit**: The configured maximum number of reason -> act -> observe cycles
  the Agent_Orchestrator performs within a single Agent_Run.
- **Tool**: A pluggable capability the agent can invoke, defined by a name, a
  description, an input schema, and an invoke operation.
- **Tool_Interface**: The abstract contract that every Tool implements, independent of
  any concrete Tool.
- **Tool_Registry**: The component that holds registered Tools and resolves a Tool by
  name for the Agent_Orchestrator.
- **RAG_Tool**: The built-in Tool that wraps the existing RAG_Service to return grounded
  answers with citations from the knowledge base.
- **Web_Search_Tool**: The built-in Tool that performs external web search through a
  pluggable search provider, and that is disabled when no search credential is
  configured.
- **Search_Provider**: The pluggable component used by the Web_Search_Tool to perform
  external web searches.
- **Tool_Call**: A request produced by the LLM_Provider to invoke a named Tool with
  arguments.
- **Tool_Result**: The output returned by a Tool after invocation, fed back into the
  Agent_Orchestrator loop as an observation.
- **Memory_Manager**: The component that provides short-term and long-term memory to the
  Agent_Orchestrator.
- **Short_Term_Memory**: The working context within a single Agent_Run (recent turns and
  scratchpad), bounded by a configured size budget.
- **Long_Term_Memory**: Persistent memory retrievable across Conversations, stored as
  embeddings in the Vector_Store and/or Postgres and retrieved by semantic similarity.
- **Size_Budget**: The configured maximum size (measured in tokens or characters) of the
  Short_Term_Memory working context.
- **Conversation**: A persistent, ordered sequence of Messages representing a multi-turn
  interaction, identified by a conversation identifier.
- **Message**: A single entry in a Conversation, having a role (user, assistant, tool,
  or system) and content.
- **Conversation_Store**: The component that persists Conversations and Messages in
  Postgres and retrieves Conversation history.
- **Streaming_Service**: The component that streams incremental Agent_Run output (tokens
  and/or intermediate steps) to the client over Server-Sent Events.
- **Trace_Recorder**: The component that records each Agent_Step for lightweight
  observability.
- **Trace**: The ordered record of Agent_Steps produced during an Agent_Run.
- **LLM_Provider**: The existing pluggable text-generation component (Groq_Provider
  primary, Fallback_Provider default) reused by the Agent_Orchestrator for reasoning and
  tool selection.
- **Fallback_Provider**: The existing deterministic, network-free LLM_Provider used when
  no external Large Language Model credential is configured.
- **RAG_Service**: The existing component that produces grounded answers with citations
  from retrieved Chunks.
- **Vector_Store**: The existing pluggable component that stores and semantically
  queries embeddings.
- **Embedding_Provider**: The existing pluggable component that converts text into
  embeddings.
- **API_Service**: The existing FastAPI application that exposes HTTP endpoints.

## Requirements

### Requirement 1: Bounded Agent Orchestration Loop

**User Story:** As a developer, I want a stateful agent loop that reasons, acts, and observes until it produces a final answer, so that the platform can autonomously solve multi-step tasks without running forever.

#### Acceptance Criteria

1. WHEN the Agent_Orchestrator receives a user request, THE Agent_Orchestrator SHALL execute a stateful graph of nodes that alternates reasoning, tool invocation, and observation until either a final answer is produced or the number of completed reason-act-observe cycles equals the Iteration_Limit.
2. THE Agent_Orchestrator SHALL carry an explicit run state across Agent_Steps that includes the conversation context, the accumulated observations, and the current iteration count represented as a non-negative integer that increments by exactly 1 after each completed reason-act-observe cycle.
3. WHEN a reasoning step determines that no further Tool invocation is required, THE Agent_Orchestrator SHALL produce a final answer and terminate the Agent_Run with a termination reason of final-answer.
4. WHEN the number of completed reason-act-observe cycles reaches the Iteration_Limit, THE Agent_Orchestrator SHALL terminate the Agent_Run, return the most recent available answer, and set the termination reason to iteration-limit-reached, such that the number of completed cycles never exceeds the Iteration_Limit.
5. THE Agent_Orchestrator SHALL obtain the Iteration_Limit from the Configuration_Manager as a positive integer between 1 and 100 inclusive, applying a bounded default value of 10 when no configured value is provided.
6. IF the Iteration_Limit obtained from the Configuration_Manager is not an integer within the range 1 to 100 inclusive, THEN THE Agent_Orchestrator SHALL reject the configured value, apply the bounded default value of 10, and record an indication that the configured limit was invalid.
7. THE Agent_Orchestrator SHALL terminate every Agent_Run with exactly one explicit termination reason that is either final-answer or iteration-limit-reached.
8. WHERE no external Large Language Model credential is configured, THE Agent_Orchestrator SHALL run the loop using the Fallback_Provider and produce a final answer that is identical for identical user requests within the same run state.

### Requirement 2: Pluggable Tool Interface and Registry

**User Story:** As a developer, I want tools defined behind a uniform interface and
registered in a registry, so that new tools can be added later without changing the
agent core.

#### Acceptance Criteria

1. THE Tool_Interface SHALL declare a name, a human-readable description, an input
   schema, and an invoke operation independently of any concrete Tool.
2. THE Tool_Registry SHALL register a Tool under its unique name and resolve a Tool by
   name on request.
3. WHEN the Agent_Orchestrator requests the set of available Tools, THE Tool_Registry
   SHALL return the name, description, and input schema of each registered Tool.
4. IF a Tool is registered under a name that already exists in the Tool_Registry, THEN
   THE Tool_Registry SHALL reject the registration and report a duplicate-tool-name
   error.
5. THE Agentic_Layer SHALL allow a new Tool to be added by implementing the
   Tool_Interface and registering it in the Tool_Registry without modifying the
   Agent_Orchestrator.

### Requirement 3: Tool Calling and Dispatch

**User Story:** As a developer, I want the LLM to decide which tool to call and have the
result fed back into the loop, so that the agent can use external capabilities to answer
requests.

#### Acceptance Criteria

1. WHEN the Agent_Orchestrator performs a reasoning step, THE Agent_Orchestrator SHALL
   present the available Tool names, descriptions, and input schemas to the
   LLM_Provider so the LLM_Provider can select a Tool.
2. WHEN the LLM_Provider produces a Tool_Call naming a registered Tool with arguments,
   THE Agent_Orchestrator SHALL resolve the Tool through the Tool_Registry and invoke it
   with those arguments.
3. WHEN a Tool returns a Tool_Result, THE Agent_Orchestrator SHALL record the
   Tool_Result as an observation in the run state and continue the loop.
4. IF the LLM_Provider produces a Tool_Call naming a Tool that is not registered in the
   Tool_Registry, THEN THE Agent_Orchestrator SHALL record a tool-not-found observation
   and continue the loop without terminating.
5. WHERE no external Large Language Model credential is configured, THE
   Agent_Orchestrator SHALL select Tools deterministically through the Fallback_Provider.

### Requirement 4: Built-in RAG Retrieval Tool

**User Story:** As a user, I want the agent to consult my knowledge base, so that its
answers are grounded in my documents with citations.

#### Acceptance Criteria

1. THE RAG_Tool SHALL implement the Tool_Interface with an input schema that accepts a
   query string and an optional result count.
2. WHEN the RAG_Tool is invoked, THE RAG_Tool SHALL delegate to the existing RAG_Service
   and SHALL NOT reimplement retrieval or generation.
3. WHEN the RAG_Service returns a grounded answer, THE RAG_Tool SHALL return a
   Tool_Result that includes the answer text and the associated Citations.
4. WHERE no external Large Language Model credential is configured, THE RAG_Tool SHALL
   return a grounded Tool_Result produced through the Fallback_Provider.

### Requirement 5: Built-in Web Search Tool with Graceful Degradation

**User Story:** As a user, I want the agent to optionally search the web, so that it can
answer questions beyond my knowledge base, while the platform still runs with no search
credential.

#### Acceptance Criteria

1. THE Web_Search_Tool SHALL implement the Tool_Interface with an input schema that
   accepts a query string.
2. THE Web_Search_Tool SHALL perform searches through a pluggable Search_Provider
   selected by the Configuration_Manager.
3. WHERE a search credential is configured, THE Tool_Registry SHALL register the
   Web_Search_Tool as available.
4. WHERE no search credential is configured, THE Web_Search_Tool SHALL report itself as
   disabled and SHALL NOT perform any external network request.
5. WHEN the Agent_Orchestrator invokes the Web_Search_Tool while the Web_Search_Tool is
   disabled, THE Web_Search_Tool SHALL return a Tool_Result indicating that web search is
   unavailable.

### Requirement 6: Short-Term Memory

**User Story:** As a user, I want the agent to remember the recent context within a conversation, so that it can reason coherently across turns within a single run.

#### Acceptance Criteria

1. WHILE an Agent_Run is in progress, THE Memory_Manager SHALL maintain a Short_Term_Memory containing the recent Messages and the agent scratchpad for that run.
2. WHEN an Agent_Run begins, THE Memory_Manager SHALL obtain the Short_Term_Memory Size_Budget, expressed as a positive count of tokens or characters, from the Configuration_Manager.
3. IF the Size_Budget obtained from the Configuration_Manager is absent, non-numeric, or less than or equal to zero, THEN THE Memory_Manager SHALL reject initialization of the Short_Term_Memory and produce an error indication that a valid Size_Budget is required, without maintaining a Short_Term_Memory.
4. WHEN adding content to the Short_Term_Memory would cause its total retained size to exceed the Size_Budget, THE Memory_Manager SHALL evict working-context entries in oldest-first (FIFO) order, excluding the current user request, until the total retained size is less than or equal to the Size_Budget.
5. THE Memory_Manager SHALL retain the current user request in the Short_Term_Memory during every add and evict operation, and after each such operation the total retained size SHALL be less than or equal to the Size_Budget.
6. IF the current user request alone exceeds the Size_Budget after all other working-context entries have been evicted, THEN THE Memory_Manager SHALL retain the current user request and produce an error indication that the Size_Budget cannot be satisfied by the current user request.

### Requirement 7: Long-Term Memory

**User Story:** As a user, I want the agent to recall relevant information from past
conversations, so that it can provide continuity across sessions.

#### Acceptance Criteria

1. WHEN the Memory_Manager persists a Long_Term_Memory entry, THE Memory_Manager SHALL
   store the entry as an embedding through the existing Embedding_Provider and
   Vector_Store.
2. WHEN the Memory_Manager retrieves Long_Term_Memory for a query, THE Memory_Manager
   SHALL return the stored entries ranked by semantic similarity to the query.
3. WHEN the Memory_Manager retrieves Long_Term_Memory for a query with a requested count
   K, THE Memory_Manager SHALL return at most K entries ordered by descending similarity.
4. IF no Long_Term_Memory entries have been stored, THEN THE Memory_Manager SHALL return
   an empty result for a retrieval request.
5. THE Memory_Manager SHALL reuse the existing Embedding_Provider and Vector_Store seams
   and SHALL NOT reimplement embedding or vector storage.

### Requirement 8: Persistent Conversation History

**User Story:** As a user, I want my multi-turn conversations persisted, so that I can
continue them and review past exchanges.

#### Acceptance Criteria

1. WHEN a request to create a Conversation is received, THE Conversation_Store SHALL
   create a Conversation with a unique conversation identifier in Postgres.
2. WHEN a Message is appended to a Conversation, THE Conversation_Store SHALL persist the
   Message with its role, content, and ordinal position within the Conversation.
3. WHEN the history of a Conversation is requested, THE Conversation_Store SHALL return
   the Messages of that Conversation in ascending order of their ordinal position.
4. IF a Message is appended to a conversation identifier that does not exist, THEN THE
   Conversation_Store SHALL create a Conversation with that identifier and persist the
   Message to the newly created Conversation.
5. WHEN an Agent_Run completes for a Conversation, THE Conversation_Store SHALL persist
   the final assistant Message to that Conversation.

### Requirement 9: Streaming Responses

**User Story:** As a user, I want to see the agent's output as it is produced, so that I get incremental feedback instead of waiting for the full response.

#### Acceptance Criteria

1. WHEN a client requests a streaming Agent_Run, THE Streaming_Service SHALL open a Server-Sent Events stream and emit the first streamed event within 5 seconds of accepting the request.
2. WHILE an Agent_Run is in progress, THE Streaming_Service SHALL emit each unit of incremental output as a separate Server-Sent Events event as it is produced, without waiting for the Agent_Run to complete.
3. THE Streaming_Service SHALL label every streamed event with exactly one distinguishable event type from the set {step, tool_call, delta, completion, error}.
4. THE Streaming_Service SHALL emit streamed events in the order in which they are produced by the Agent_Run, preserving that order end-to-end for the client.
5. WHEN the Agent_Run produces intermediate Agent_Steps, THE Streaming_Service SHALL emit each Agent_Step, including each Tool_Call, as a distinct streamed event of type step or tool_call respectively.
6. WHEN the Agent_Run produces its final answer, THE Streaming_Service SHALL emit exactly one terminal event of type completion and then close the stream.
7. WHERE no external Large Language Model credential is configured, THE Streaming_Service SHALL stream deterministic incremental output produced through the Fallback_Provider, such that two runs with identical input produce identical ordered sequences of streamed events.
8. IF an error occurs during a streaming Agent_Run, THEN THE Streaming_Service SHALL emit exactly one terminal event of type error that indicates the failure and then close the stream, and SHALL NOT emit a completion event for that stream.
9. THE Streaming_Service SHALL emit exactly one terminal event (either completion or error) per stream and SHALL close the stream after emitting that terminal event.

### Requirement 10: Observability Tracing of Agent Steps

**User Story:** As a developer, I want each agent step recorded, so that I can inspect
what the agent did and later extend observability without rework.

#### Acceptance Criteria

1. WHEN an Agent_Step executes, THE Trace_Recorder SHALL record a Trace entry containing
   the step type, the associated Agent_Run identifier, and the ordinal position of the
   step.
2. WHEN the Agent_Orchestrator invokes a Tool, THE Trace_Recorder SHALL record the Tool
   name and the outcome of the invocation in the Trace.
3. WHEN an Agent_Run completes, THE Trace_Recorder SHALL produce a Trace whose entries
   are ordered by their ordinal position.
4. THE Trace_Recorder SHALL expose the Trace of an Agent_Run through a defined interface
   so a later observability phase can consume it without modifying the Agent_Orchestrator.

### Requirement 11: Safety and Execution Bounds

**User Story:** As a developer, I want the agent to guard against runaway loops and bad
tool inputs, so that the platform stays stable and predictable.

#### Acceptance Criteria

1. THE Agent_Orchestrator SHALL enforce the Iteration_Limit as an upper bound on the
   number of reason-act-observe cycles within an Agent_Run.
2. WHEN a Tool_Call provides arguments that do not conform to the Tool input schema, THE
   Agent_Orchestrator SHALL reject the invocation, record a validation-error observation,
   and continue the loop without invoking the Tool.
3. IF a Tool raises an error during invocation, THEN THE Agent_Orchestrator SHALL record
   a tool-execution-error observation and continue the Agent_Run without terminating the
   process.
4. WHEN a Tool_Call is validated before invocation, THE Agent_Orchestrator SHALL invoke
   the Tool only if the arguments conform to the Tool input schema.

### Requirement 12: Reuse of Existing Pluggable Seams

**User Story:** As a developer, I want the agentic layer to reuse the existing platform
seams, so that behavior stays consistent and the keyless promise is preserved.

#### Acceptance Criteria

1. THE Agent_Orchestrator SHALL use the existing LLM_Provider seam for reasoning and Tool
   selection and SHALL NOT introduce a separate text-generation implementation.
2. THE RAG_Tool SHALL use the existing RAG_Service and SHALL NOT reimplement retrieval or
   grounding.
3. THE Memory_Manager SHALL use the existing Embedding_Provider and Vector_Store for
   Long_Term_Memory and SHALL NOT reimplement embedding or vector storage.
4. THE Agentic_Layer SHALL expose its endpoints through the existing API_Service using
   the existing uniform error envelope.

### Requirement 13: Keyless Runnability and Automated Testing

**User Story:** As a developer, I want the agentic layer runnable and testable with no
external credentials, so that I can verify it locally before adding paid providers.

#### Acceptance Criteria

1. THE Agentic_Layer SHALL operate using only free-tier compatible dependencies when no
   external Large Language Model credential and no search credential are configured.
2. THE Agentic_Layer SHALL include automated tests for the Agent_Orchestrator loop, Tool
   dispatch, the Memory_Manager, and the Streaming_Service.
3. WHEN a developer runs the documented test command with no external credentials
   configured, THE Agentic_Layer SHALL execute its automated test suite and report a pass
   or fail result.
4. THE Agentic_Layer SHALL provide automated tests that exercise the bounded loop
   termination behavior using the Fallback_Provider.

### Requirement 14: Documented Design Decisions

**User Story:** As a developer learning the stack, I want the agentic layer's design
decisions documented, so that I understand why it is built this way.

#### Acceptance Criteria

1. THE Agentic_Layer SHALL document the rationale for each major architectural decision
   of the agentic layer in a written record within the repository.
2. THE Agentic_Layer SHALL document how a new Tool and a new agent node type are added
   without modifying the Agent_Orchestrator.
