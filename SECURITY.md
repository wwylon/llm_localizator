# Security

## Reporting

Open a **private** GitHub security advisory on `wwylon/llm_localizator`, or contact the
maintainer listed on the GitHub profile. Do not post exploit details in public issues.

## Deployment notes

- The review server binds to `127.0.0.1`. Every POST needs the session token printed at
  startup (`X-LLM-Token`); requests from a non-localhost `Origin` are refused. Do not expose
  it on a public interface.
- Catalogues, imports, context files and fetched engine files are treated as untrusted input.
- Cloud providers (Anthropic, OpenAI, DeepSeek, DeepL) run only when you set
  `[privacy] allow_cloud = true` and a monthly budget. API keys are read from the
  environment and are never written to project files.
- llm_localizator sends no telemetry. It makes network calls only to services you configure
  (the model provider, a webhook, a remote content API) and, when you run `engine fetch`,
  to the engine host.
