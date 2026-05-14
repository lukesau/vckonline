/**
 * Cookie `vck_client` (JSON): player_id, game_id, display_name, counter, …
 * Path=/, SameSite=Lax. Migrates legacy localStorage playerId / gameId once.
 */
(function (global) {
  var COOKIE_NAME = 'vck_client';
  var MAX_AGE_SEC = 3600 * 24 * 400;

  function parseCookie() {
    var prefix = COOKIE_NAME + '=';
    var all = document.cookie ? document.cookie.split(';') : [];
    var i;
    var p;
    for (i = 0; i < all.length; i++) {
      p = all[i].replace(/^\s+/, '');
      if (p.indexOf(prefix) !== 0) continue;
      try {
        var o = JSON.parse(decodeURIComponent(p.substring(prefix.length)));
        return o && typeof o === 'object' ? o : {};
      } catch (e) {
        return {};
      }
    }
    return {};
  }

  function hasId(v) {
    return String(v || '').trim().length > 0;
  }

  function migrateLsInto(meta) {
    var migrated = false;
    try {
      var pid = localStorage.getItem('playerId');
      var gid = localStorage.getItem('gameId');
      if (pid && !hasId(meta.player_id)) {
        meta.player_id = pid;
        migrated = true;
      }
      if (gid && !hasId(meta.game_id)) {
        meta.game_id = gid;
        migrated = true;
      }
      if (migrated) {
        localStorage.removeItem('playerId');
        localStorage.removeItem('gameId');
      }
    } catch (e) {
      /* ignore */
    }
    return migrated;
  }

  function read() {
    var meta = parseCookie();
    if (migrateLsInto(meta)) write(meta);
    return meta;
  }

  function write(meta) {
    var raw = encodeURIComponent(JSON.stringify(meta || {}));
    document.cookie =
      COOKIE_NAME + '=' + raw + ';path=/;max-age=' + MAX_AGE_SEC + ';SameSite=Lax';
  }

  function patch(updates) {
    var meta = read();
    var k;
    var ck;
    for (k in updates) {
      if (!Object.prototype.hasOwnProperty.call(updates, k)) continue;
      if (updates[k] === null || updates[k] === undefined) {
        delete meta[k];
        continue;
      }
      if (k === 'counter' && typeof updates.counter === 'object' && updates.counter) {
        meta.counter = meta.counter || {};
        for (ck in updates.counter) {
          if (Object.prototype.hasOwnProperty.call(updates.counter, ck))
            meta.counter[ck] = updates.counter[ck];
        }
      } else {
        meta[k] = updates[k];
      }
    }
    write(meta);
    return meta;
  }

  global.VCK_CLIENT_META = { read: read, write: write, patch: patch };
})(typeof window !== 'undefined' ? window : this);
