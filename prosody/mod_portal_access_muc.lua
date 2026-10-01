-- Zugriffsregeln des Portals für die Konferenz-Komponente (MUC), geladen über XMPP_MUC_MODULES.
--
-- 1. Zweite Sicherung zu mod_portal_access: Wer ohne Token direkt einem Portal-Raum beitreten
--    will, wird abgewiesen. Interne Teilnehmer (Fokus, Jibri, Jigasi) melden sich über eigene
--    Domains an und sind ausgenommen.
-- 2. Moderation in Portal-Räumen: Portal-Benutzer (Token mit moderator=true) werden beim Betreten
--    Moderator. Gäste (Gastlink, persönlicher Link) werden nie automatisch befördert: Versucht
--    Jicofo (Auto-Owner), einem Gast die Moderation zu geben, lehnen wir das ab. Ein Moderator
--    kann einen Gast weiterhin bewusst von Hand zum Moderator machen.
-- 3. Chatprotokoll: Gruppen-Chatnachrichten in Portal-Räumen werden tageweise als JSON-Zeilen
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
local focus_domain = module:get_option_string("portal_focus_domain", main_domain and ("auth." .. main_domain) or nil);
local mod_muc = module:depends("muc");
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

-- --- Moderation ------------------------------------------------------------------

local function is_token_moderator(session)
    if not session or session.auth_token == nil then return false; end
    local user = session.jitsi_meet_context_user;
    return type(user) == "table" and (user.moderator == true or user.moderator == "true");
end

local function session_of(room, bare_jid)
    for _, occupant in room:each_occupant() do
        if occupant.bare_jid == bare_jid then
            for real_jid in occupant:each_session() do
                local session = prosody.full_sessions[real_jid];
                if session then return session; end
            end
        end
    end
    return nil;
end

local function is_portal_room(room)
    local node = jid.split(room.jid);
    return node ~= nil and load_state().rooms[string.lower(node)] == true;
end

-- Portal-Benutzer werden beim Betreten eines Portal-Raums Moderator (unabhängig von der Reihenfolge)
module:hook("muc-occupant-pre-join", function(event)
    local room, occupant, session = event.room, event.occupant, event.origin;
    if not session or (main_domain and session.host ~= main_domain) then return; end
    if not is_portal_room(room) or not is_token_moderator(session) then return; end
    room:set_affiliation(true, occupant.bare_jid, "owner");
    occupant.role = "moderator";
end, -3.5);

-- Automatische Beförderung durch Jicofo (Auto-Owner) in Portal-Räumen nur für Portal-Benutzer
local function filter_focus_grants(event)
    local origin, stanza = event.origin, event.stanza;
    if not focus_domain or jid.host(stanza.attr.from or "") ~= focus_domain then return; end
    local room = mod_muc.get_room_from_jid(jid.bare(stanza.attr.to));
    if not room or not is_portal_room(room) then return; end
    local query = stanza.tags[1];
    if not query then return; end
    for _, item in ipairs(query.tags) do
        if item.name == "item" and (item.attr.affiliation == "owner" or item.attr.role == "moderator") then
            local target = item.attr.jid and jid.bare(item.attr.jid);
            if not target and item.attr.nick then
                local occupant = room:get_occupant_by_nick(room.jid .. "/" .. item.attr.nick);
                target = occupant and occupant.bare_jid;
            end
            if target and not is_token_moderator(session_of(room, target)) then
                module:log("info", "Automatische Moderation für Gast %s in %s abgelehnt", target, room.jid);
                origin.send(st.error_reply(stanza, "auth", "forbidden"));
                return true;
            end
        end
    end
end
module:hook("iq-set/bare/http://jabber.org/protocol/muc#admin:query", filter_focus_grants, 5);
module:hook("iq-set/host/http://jabber.org/protocol/muc#admin:query", filter_focus_grants, 5);

-- --- Chatprotokoll ------------------------------------------------------------------

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
