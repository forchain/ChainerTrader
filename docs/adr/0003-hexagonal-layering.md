# Hexagonal layering for the trading core

We decided to organize the application as a hexagonal architecture with three layers: `core/` (domain and application), `adapters/` (inbound and outbound), and a single composition root at the package entry point.

Dependency direction is one-way: adapters depend on core, never the reverse. Inside core, use cases depend on domain models and on the interfaces defined alongside them. No module under `trader/core` may import `trader.adapters` or a framework (FastAPI, Tortoise, backtrader, ccxt, Binance SDKs); `tests/test_import_direction.py` enforces this with an AST scan.

All outbound ports (repositories, clients, stores, gateways) are defined in the application layer and implemented under `adapters/outbound/`. Inbound HTTP and CLI code lives under `adapters/inbound/` and only parses external input, calls use cases, and translates domain errors. Only the composition root may instantiate concrete adapters and inject them into use cases and inbound adapters.

Business code moves into this structure incrementally. ADR-0001 and ADR-0002 remain in force, and every migration step must preserve their behavior, the HTTP and CLI contracts, and the database schema.
