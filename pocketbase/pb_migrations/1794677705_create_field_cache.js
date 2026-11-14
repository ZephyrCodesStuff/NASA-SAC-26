/// <reference path="../pb_data/types.d.ts" />
// Response cache used by web/src/providers (catasto.py, nasa.py): one record per cache_key.
// Records are immutable from the API: create once, never update or delete (superusers can).
migrate(
  (app) => {
    const collection = new Collection({
      type: "base",
      name: "field_cache",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: null,
      deleteRule: null,
      fields: [
        { name: "cache_key", type: "text", required: true, max: 200 },
        { name: "payload", type: "json", required: true, maxSize: 10 * 1024 * 1024 },
        { name: "created", type: "autodate", onCreate: true, onUpdate: false },
      ],
      indexes: [
        "CREATE UNIQUE INDEX idx_field_cache_key ON field_cache (cache_key)",
      ],
    });
    app.save(collection);
  },
  (app) => {
    const collection = app.findCollectionByNameOrId("field_cache");
    app.delete(collection);
  }
);
