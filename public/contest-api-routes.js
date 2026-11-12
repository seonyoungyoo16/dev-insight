// Generated from api/openapi.json by tools/api_contract.py. Do not edit.
"use strict";

/**
 * @typedef {Object} BoardState
 * @property {Array<object>} sources
 * @property {Array<object>} contests
 * @property {boolean} running
 * @property {string} today
 */
window.contestApiRoutes = {
  "listContests": {
    "path": "/api/contests",
    "method": "GET"
  },
  "refreshContests": {
    "path": "/api/refresh",
    "method": "POST",
    "body": {}
  }
};
