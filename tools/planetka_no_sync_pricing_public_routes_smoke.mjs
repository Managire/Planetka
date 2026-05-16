#!/usr/bin/env node
/*
 * Named smoke-test entrypoint for the public-route pricing invariant.
 *
 * The implementation lives in planetka_quote_read_only_health_gate.mjs because
 * that gate also exercises materialized quote-row behavior.
 */

import "./planetka_quote_read_only_health_gate.mjs";
