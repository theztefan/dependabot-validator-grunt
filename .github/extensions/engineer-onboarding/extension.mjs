import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

import { CanvasError, createCanvas, joinSession } from "@github/copilot-sdk/extension";

import { renderOnboardingHtml, topicSummaries } from "./renderer.mjs";

const servers = new Map();
let extensionSession;

function writeResponse(response, statusCode, contentType, body) {
    response.statusCode = statusCode;
    response.setHeader("Content-Type", contentType);
    response.setHeader("Cache-Control", "no-store");
    response.setHeader(
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'self'",
    );
    response.end(body);
}

function requireTopic(input) {
    const topic = input?.topic;
    if (typeof topic !== "string" || !Object.hasOwn(topicSummaries, topic)) {
        throw new CanvasError("invalid_topic", "Select a declared onboarding topic");
    }
    return topic;
}

async function startServer(instanceId, initialTopic) {
    const token = randomUUID();
    const rootPath = `/${token}/`;
    const eventsPath = `/${token}/events`;
    const state = { topic: initialTopic, clients: new Set() };
    const server = createServer((request, response) => {
        const url = new URL(request.url ?? "/", "http://127.0.0.1");
        if (request.method === "GET" && url.pathname === rootPath) {
            writeResponse(
                response,
                200,
                "text/html; charset=utf-8",
                renderOnboardingHtml({ instanceId, initialTopic: state.topic }),
            );
            return;
        }
        if (request.method === "GET" && url.pathname === eventsPath) {
            response.statusCode = 200;
            response.setHeader("Content-Type", "text/event-stream; charset=utf-8");
            response.setHeader("Cache-Control", "no-store");
            response.setHeader("Connection", "keep-alive");
            response.write(`event: topic\ndata: ${JSON.stringify(state.topic)}\n\n`);
            state.clients.add(response);
            request.on("close", () => state.clients.delete(response));
            return;
        }
        {
            writeResponse(response, 404, "text/plain; charset=utf-8", "Not found");
        }
    });
    await new Promise((resolve, reject) => {
        const onError = (error) => reject(error);
        server.once("error", onError);
        server.listen(0, "127.0.0.1", () => {
            server.off("error", onError);
            resolve();
        });
    });
    server.on("error", (error) => {
        void extensionSession?.log(`Onboarding canvas server error: ${error.message}`, {
            level: "error",
        });
    });
    const address = server.address();
    if (!address || typeof address === "string") {
        await new Promise((resolve) => server.close(resolve));
        throw new Error("Unable to allocate a loopback port for the onboarding canvas");
    }
    return {
        server,
        state,
        url: `http://127.0.0.1:${address.port}${rootPath}`,
    };
}

function startServerOnce(instanceId, initialTopic) {
    let pending = servers.get(instanceId);
    if (!pending) {
        pending = startServer(instanceId, initialTopic).catch((error) => {
            if (servers.get(instanceId) === pending) {
                servers.delete(instanceId);
            }
            throw error;
        });
        servers.set(instanceId, pending);
    }
    return pending;
}

function showTopic(entry, topic) {
    entry.state.topic = topic;
    const event = `event: topic\ndata: ${JSON.stringify(topic)}\n\n`;
    for (const client of entry.state.clients) {
        client.write(event);
    }
}

extensionSession = await joinSession({
    canvases: [
        createCanvas({
            id: "engineer-onboarding",
            displayName: "Engineer onboarding",
            description:
                "Interactive guide to running, understanding, and safely customizing Dependabot Validator Grunt.",
            inputSchema: {
                type: "object",
                additionalProperties: false,
                properties: {
                    topic: {
                        type: "string",
                        enum: Object.keys(topicSummaries),
                        description: "The onboarding topic to show first.",
                    },
                },
            },
            actions: [
                {
                    name: "get_topic_summary",
                    description:
                        "Return the key commands, files, and guardrails for one onboarding topic.",
                    inputSchema: {
                        type: "object",
                        additionalProperties: false,
                        required: ["topic"],
                        properties: {
                            topic: {
                                type: "string",
                                enum: Object.keys(topicSummaries),
                            },
                        },
                    },
                    handler: (ctx) => topicSummaries[requireTopic(ctx.input)],
                },
                {
                    name: "show_topic",
                    description: "Navigate an open onboarding canvas to a selected topic.",
                    inputSchema: {
                        type: "object",
                        additionalProperties: false,
                        required: ["topic"],
                        properties: {
                            topic: {
                                type: "string",
                                enum: Object.keys(topicSummaries),
                            },
                        },
                    },
                    handler: async (ctx) => {
                        const topic = requireTopic(ctx.input);
                        const pending = servers.get(ctx.instanceId);
                        if (!pending) {
                            throw new CanvasError(
                                "canvas_not_open",
                                "The onboarding canvas instance is not open",
                            );
                        }
                        const entry = await pending;
                        showTopic(entry, topic);
                        return topicSummaries[topic];
                    },
                },
            ],
            open: async (ctx) => {
                const requestedTopic = ctx.input?.topic;
                const initialTopic =
                    typeof requestedTopic === "string" &&
                    Object.hasOwn(topicSummaries, requestedTopic)
                        ? requestedTopic
                        : "overview";
                const entry = await startServerOnce(ctx.instanceId, initialTopic);
                showTopic(entry, initialTopic);
                return {
                    title: "Dependabot Validator Grunt onboarding",
                    status:
                        "Runbook, full flows, architecture, customization, evaluation, and safety",
                    url: entry.url,
                };
            },
            onClose: async (ctx) => {
                const pending = servers.get(ctx.instanceId);
                if (!pending) {
                    return;
                }
                servers.delete(ctx.instanceId);
                const entry = await pending;
                for (const client of entry.state.clients) {
                    client.end();
                }
                entry.state.clients.clear();
                await new Promise((resolve) => entry.server.close(resolve));
            },
        }),
    ],
});
