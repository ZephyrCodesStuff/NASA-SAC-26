/// <reference path="../pb_data/types.d.ts" />
migrate(
  (app) => {
    const collection = new Collection({
      type: "base",
      name: "app_users",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: null,
      fields: [
        { name: "email", type: "email", required: true },
        { name: "name", type: "text", required: true },
        { name: "role", type: "text", required: false },
        { name: "password_hash", type: "text", required: true },
        { name: "is_demo", type: "bool", required: false },
      ],
      indexes: [
        "CREATE UNIQUE INDEX idx_app_users_email ON app_users (email)",
      ],
    });
    app.save(collection);
  },
  (app) => {
    const collection = app.findCollectionByNameOrId("app_users");
    app.delete(collection);
  }
);
