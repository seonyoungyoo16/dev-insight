"use strict";

(() => {
  const routes = window.contestApiRoutes;

  /** @returns {Promise<BoardState>} */
  async function request(operation) {
    const route = routes[operation];
    const options = { method: route.method };
    if (route.body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(route.body);
    }
    const response = await fetch(route.path, options);
    if (!response.ok) throw new Error("Unable to load contests");
    return response.json();
  }

  window.contestApi = Object.freeze({
    listContests: () => request("listContests"),
    refreshContests: () => request("refreshContests"),
  });
})();
