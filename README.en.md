# NeuroEntrepreneur AI Coach

[Documentation complète en français](README.md)

NeuroEntrepreneur is a conversational coach that helps entrepreneurs clarify an idea,
assess a potential offer, build a task plan and track progress.

- LangGraph manages the conversation and proposals. Plans and task changes can be reviewed before confirmation.
- Streamlit provides the project workspace, task list, conversation history and notifications.
- SQLite stores project data and conversation checkpoints. A separate worker checks deadlines.
- OpenAI powers the coach when configured. Tavily and Exa provide optional web research.

See the [installation instructions](README.md#installation), [architecture](docs/ARCHITECTURE.md)
and [deployment guide](deploy/README.md). Use a local environment file based on
[.env.example](.env.example) to configure API credentials.

This is a portfolio prototype. The local user profiles do not provide authentication.
Released under the [MIT License](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md).
