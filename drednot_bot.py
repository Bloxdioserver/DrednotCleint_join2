// ==UserScript==
// @name         Drednot.io Interactive Bot Controller
// @namespace    http://tampermonkey.net/
// @version      3.0
// @description  Control your bot in-game with !join, !leave, and !say commands.
// @author       You
// @match        https://drednot.io/*
// @grant        GM_xmlhttpRequest
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    // --- CONFIGURATION ---

    // A list of all your interactive bot server URLs.
    const BOT_SERVER_URLS = [
        'https://drednotclient-join1.onrender.com', // Base URL, no endpoint
        'https://drednotcleint-join2.onrender.com'  // Using the "cleint" spelling
    ];

    // The API key required by your servers.
    const API_KEY = 'drednot123';

    // --- SCRIPT STATE ---
    let myUsername = 'Detecting...';
    let currentShipId = null;

    console.log('[BotController] Script loaded. Ready for your commands!');

    /**
     * Sends a generic request to a bot server.
     * @param {string} serverUrl The base URL of the server.
     * @param {string} endpoint The API endpoint to call (e.g., '/join-request').
     * @param {object} payload The JSON data to send in the request body.
     */
    function sendApiRequest(serverUrl, endpoint, payload) {
        const fullUrl = serverUrl + endpoint;
        console.log(`[BotController] Sending request to ${fullUrl}`);

        GM_xmlhttpRequest({
            method: "POST",
            url: fullUrl,
            headers: {
                "Content-Type": "application/json",
                "x-api-key": API_KEY
            },
            data: JSON.stringify(payload),
            onload: function(response) {
                if (response.status === 200) {
                    console.log(`[BotController] Server at ${serverUrl} acknowledged the '${endpoint}' request.`);
                } else {
                    console.error(`[BotController] Server at ${serverUrl} returned an error for '${endpoint}': ${response.status}`, response.responseText);
                }
            },
            onerror: function(response) {
                console.error(`[BotController] Network error connecting to ${serverUrl}.`, response);
            }
        });
    }

    /**
     * Watches the chat for new messages to capture the Ship ID and listen for commands.
     */
    function monitorChat() {
        const chatContent = document.getElementById("chat-content");
        if (!chatContent) {
            setTimeout(monitorChat, 1000);
            return;
        }

        console.log('[BotController] Chat monitor is now active.');

        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType !== 1 || node.tagName !== 'P') return;

                    const pText = node.textContent || "";

                    // 1. Capture the Ship ID when you first join.
                    if (pText.includes("Joined ship '")) {
                        const match = pText.match(/{[A-Z\d]+}/);
                        if (match && match[0]) {
                            currentShipId = match[0];
                            console.log(`[BotController] Captured your Ship ID: ${currentShipId}`);
                        }
                    }

                    // 2. Check for commands from the user.
                    const colonIdx = pText.indexOf(':');
                    if (colonIdx === -1) return;

                    const bdiElement = node.querySelector("bdi");
                    if (!bdiElement) return;

                    const username = bdiElement.innerText.trim();
                    const message = pText.substring(colonIdx + 1).trim(); // Keep original case for !say

                    // 3. Check if the command is from YOU.
                    if (username === myUsername && message.startsWith('!')) {
                        const parts = message.substring(1).split(/ +/);
                        const command = parts.shift().toLowerCase();
                        const args = parts;

                        switch (command) {
                            case 'join':
                                if (currentShipId) {
                                    console.log(`[BotController] Sending join command for ship ${currentShipId}...`);
                                    // Send join request to the FIRST bot server only.
                                    if (BOT_SERVER_URLS.length > 0) {
                                        sendApiRequest(BOT_SERVER_URLS[0], '/join-request', { shipId: currentShipId });
                                    }
                                } else {
                                    console.error('[BotController] Cannot use !join, your Ship ID has not been captured yet.');
                                }
                                break;
                            
                            case 'join2':
                                if (currentShipId) {
                                     console.log(`[BotController] Sending join command for ship ${currentShipId} to BOTH bots...`);
                                     // Send join request to BOTH bot servers.
                                     if(BOT_SERVER_URLS.length >= 2) {
                                         sendApiRequest(BOT_SERVER_URLS[0], '/join-request', { shipId: currentShipId });
                                         sendApiRequest(BOT_SERVER_URLS[1], '/join-request', { shipId: currentShipId });
                                     } else {
                                         console.error('[BotController] Not enough bot servers configured for !join2 command.');
                                     }
                                } else {
                                    console.error('[BotController] Cannot use !join2, your Ship ID has not been captured yet.');
                                }
                                break;

                            case 'leave':
                                console.log('[BotController] Sending leave command to all bots...');
                                // Send leave request to ALL bot servers.
                                BOT_SERVER_URLS.forEach(server => {
                                    sendApiRequest(server, '/leave-request', {});
                                });
                                break;

                            case 'say':
                                if (args.length > 0) {
                                    const messageToSay = args.join(' ');
                                    console.log(`[BotController] Sending say command to all bots: "${messageToSay}"`);
                                    // Send say request to ALL bot servers.
                                    BOT_SERVER_URLS.forEach(server => {
                                        sendApiRequest(server, '/say-request', { message: messageToSay });
                                    });
                                } else {
                                    console.log('[BotController] Ignoring empty !say command.');
                                }
                                break;
                        }
                    }
                });
            });
        });

        observer.observe(chatContent, { childList: true });
    }

    /**
     * Finds your username from the game's UI to ensure only you can trigger the command.
     */
    function findMyUsername() {
        const nameElement = document.querySelector(".main-ui-title");
        if (nameElement && nameElement.textContent) {
            myUsername = nameElement.textContent.trim();
            console.log(`[BotController] Identified user as: "${myUsername}".`);
        } else {
            // If the UI isn't ready, try again in a second.
            setTimeout(findMyUsername, 1000);
        }
    }

    function initialize() {
        findMyUsername();
        monitorChat();
    }
    
    // Wait for the page to fully load before running the script.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }

})();
