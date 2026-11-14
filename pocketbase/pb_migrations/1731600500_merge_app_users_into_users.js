/// <reference path="../pb_data/types.d.ts" />
migrate(
  (app) => {
    const users = app.findCollectionByNameOrId("_pb_users_auth_");
    let changed = false;
    if (!users.fields.getByName("password_hash")) {
      users.fields.add(new TextField({ name: "password_hash", required: false }));
      changed = true;
    }
    if (!users.fields.getByName("is_demo")) {
      users.fields.add(new BoolField({ name: "is_demo", required: false }));
      changed = true;
    }
    if (changed) {
      app.save(users);
    }

    try {
      const appUsers = app.findCollectionByNameOrId("app_users");
      app.delete(appUsers);
    } catch (_) {}
  },
  (app) => {
    // No-op down migration; app_users was consolidated into users
  }
);
