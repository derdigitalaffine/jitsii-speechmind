-- Zugriffsregeln des Portals für die Konferenz-Komponente (MUC), geladen über XMPP_MUC_MODULES.
--
-- 1. Zweite Sicherung zu mod_portal_access: Wer ohne Token direkt einem Portal-Raum beitreten
--    will, wird abgewiesen. Interne Teilnehmer (Fokus, Jibri, Jigasi) melden sich über eigene
--    Domains an und sind ausgenommen.
-- 2. Chatprotokoll: Gruppen-Chatnachrichten in Portal-Räumen werden tageweise als JSON-Zeilen
--    nach /portal-chat/<raum>/<JJJJ-MM-TT>.jsonl geschrieben. Das Portal hängt die Nachrichten,
--    die während einer Aufnahme geschrieben wurden, als "Chatprotokoll" an die Aufnahme und
--    löscht die Rohdateien nach kurzer Zeit. Private Nachrichten und freie Räume: nie.

local st = require "util.stanza";
local jid = require "util.jid";
local json = require "util.json";
local lfs = require "lfs";

local state_file = module:get_option_string("portal_rooms_file", "/portal-rooms/rooms.json");
local chat_dir = module:get_option_string("portal_chat_dir", "/portal-chat");
local main_domain = module:get_option_string("muc_mapper_domain_base");
local state = { anonymous = false, rooms = {} };
local loaded_mtime = nil;

local function load_state()
    local attr = lfs.attributes(state_file);
    if not attr then
        state = { anonymous = false, rooms = {} };
        loaded_mtime = nil;
        return state;
    end
    if attr.modification == loaded_mtime then return state; end
    local f = io.open(state_file, "r");
    if not f then return state; end
    local parsed = json.decode(f:read("*a"));
    f:close();
    if type(parsed) ~= "table" then
        state = { anonymous = false, rooms = {} };
        return state;
    end
    local rooms = {};
    for _, name in ipairs(parsed.rooms or {}) do rooms[string.lower(name)] = true; end
    state = { anonymous = parsed.anonymous == true, rooms = rooms };
    loaded_mtime = attr.modification;
    return state;
end

module:hook("muc-occupant-pre-join", function(event)
    local session, room = event.origin, event.room;
    if not session or session.auth_token ~= nil then return; end
    -- Nur normale Clients der Haupt-Domain prüfen (nicht Fokus, Jibri, Jigasi)
    if main_domain and session.host ~= main_domain then return; end
    local node = jid.split(room.jid);
    node = node and string.lower(node);
    local s = load_state();
    if node and (s.rooms[node] or not s.anonymous) then
        module:log("info", "Beitritt ohne Token zu %s abgelehnt", node);
        session.send(st.error_reply(event.stanza, "auth", "forbidden"));
        return true;
    end
end, 10);

-- Anzeigename der schreibenden Person: aus der Nachricht, sonst aus der Anwesenheit, sonst aus dem Token
local function sender_name(event)
    local nick = event.stanza:get_child_text("nick", "http://jabber.org/protocol/nick");
    if (not nick or nick == "") and event.occupant and event.occupant.get_presence then
        local presence = event.occupant:get_presence();
        nick = presence and presence:get_child_text("nick", "http://jabber.org/protocol/nick");
    end
    if (not nick or nick == "") and event.origin and event.origin.jitsi_meet_context_user then
        nick = event.origin.jitsi_meet_context_user.name;
    end
    if not nick or nick == "" then nick = "Teilnehmer:in"; end
    return nick;
end

module:hook("muc-occupant-groupchat", function(event)
    local session = event.origin;
    if not session or (main_domain and session.host ~= main_domain) then return; end
    local body = event.stanza:get_child_text("body");
    if not body or body == "" then return; end
    local node = jid.split(event.room.jid);
    node = node and string.lower(node);
    if not node or not node:match("^[a-z0-9._-]+$") then return; end
    if not load_state().rooms[node] then return; end  -- nur Portal-Räume
    local dir = chat_dir .. "/" .. node;
    if not lfs.attributes(dir) then lfs.mkdir(dir); end
    local now = os.time();
    local f = io.open(dir .. "/" .. os.date("!%Y-%m-%d", now) .. ".jsonl", "a");
    if not f then
        module:log("warn", "Chatprotokoll für %s nicht schreibbar (%s)", node, chat_dir);
        return;
    end
    f:write(json.encode({ ts = now, name = sender_name(event), text = body:sub(1, 4000) }), "\n");
    f:close();
end, -10);
