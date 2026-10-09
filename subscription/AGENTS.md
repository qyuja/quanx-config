# Private subscription deployment

- Deployed on the existing HTTPS subscription host under `/opt/projects/quanx-subscription`.
- Keep runtime settings, bearer keys, SSH private keys and generated client exports outside Git. Do not print their values in logs or review evidence.
- The repository is read through a read-only GitHub deploy key. Japan node exports use a separate SSH key restricted to the export command; it must not permit an interactive shell or forwarding.
- Do not change sing-box credentials, listening ports, DNS, certificate validation or existing Nginx routes as part of subscription publishing.
- Publish native Quantumult X nodes. AnyTLS certificate verification stays enabled; the Japan self-signed certificate requires its public-key pin.
- Build and validate a separate publication, then switch `current` atomically. Do not alias a mutable Git checkout or expose `.git`, runtime settings, TLS private keys or server configurations.
- Test real HTTPS requests with a valid key, absent key, wrong key and traversal paths. Test node connectivity separately from subscription downloading and phone activation.
- Changing the access key requires first disabling and reloading the old Nginx location, then generating the new publication/location and reloading again. This prevents the old key from retrieving a configuration containing its replacement.
