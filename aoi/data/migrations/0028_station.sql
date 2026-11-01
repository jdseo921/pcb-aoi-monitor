-- REQ-SET-011: the station's ID, which About shows and the support bundle carries, so a ticket names the station without
-- a person's name or the PC's. One UUID4, made when this migration runs, kept with the workspace (a copied workspace
-- keeps it; the licence's machine ID is F.2's, REQ-SET-010).

CREATE TABLE station (
    uuid TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO station(uuid, created_at) VALUES (
    lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))), 2)
        || '-' || substr('89ab', 1 + (random() & 3), 1) || substr(lower(hex(randomblob(2))), 2) || '-'
        || lower(hex(randomblob(6))),
    strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
);
