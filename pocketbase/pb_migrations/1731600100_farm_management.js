/// <reference path="../pb_data/types.d.ts" />
migrate(
  (app) => {
    // 1. Extend built-in `users` Auth collection with `role`
    const users = app.findCollectionByNameOrId("_pb_users_auth_");
    if (!users.fields.getByName("role")) {
      users.fields.add(
        new SelectField({
          name: "role",
          values: ["farm_admin", "viewer"],
          maxSelect: 1,
          required: false,
        })
      );
      app.save(users);
    }

    // 2. Create `farms` Base collection
    const farms = new Collection({
      type: "base",
      name: "farms",
      listRule: "is_public_demo = true || owner = @request.auth.id || viewers.id ?= @request.auth.id",
      viewRule: "is_public_demo = true || owner = @request.auth.id || viewers.id ?= @request.auth.id",
      createRule: '@request.auth.id != "" && @request.auth.role = "farm_admin" && @request.body.owner = @request.auth.id',
      updateRule: "owner = @request.auth.id",
      deleteRule: "owner = @request.auth.id",
      fields: [
        { name: "name", type: "text", required: true },
        new RelationField({
          name: "owner",
          collectionId: users.id,
          maxSelect: 1,
          required: true,
        }),
        new RelationField({
          name: "viewers",
          collectionId: users.id,
          maxSelect: 99,
          required: false,
        }),
        { name: "is_public_demo", type: "bool", required: false },
        { name: "constraints", type: "json", required: false },
      ],
    });
    app.save(farms);

    // 3. Create `user_plots` Base collection
    const userPlots = new Collection({
      type: "base",
      name: "user_plots",
      listRule: "farm.is_public_demo = true || farm.owner = @request.auth.id || farm.viewers.id ?= @request.auth.id",
      viewRule: "farm.is_public_demo = true || farm.owner = @request.auth.id || farm.viewers.id ?= @request.auth.id",
      createRule: "farm.owner = @request.auth.id",
      updateRule: "farm.owner = @request.auth.id",
      deleteRule: "farm.owner = @request.auth.id",
      fields: [
        new RelationField({
          name: "farm",
          collectionId: farms.id,
          maxSelect: 1,
          cascadeDelete: true,
          required: true,
        }),
        { name: "cadastral_ref", type: "text", required: false },
        { name: "label", type: "text", required: true },
        { name: "area_ha", type: "number", required: false },
        { name: "centroid", type: "json", required: false },
        { name: "geometry", type: "json", required: true },
        { name: "soil_override", type: "json", required: false },
        { name: "baseline_rotation", type: "json", required: false },
        { name: "active_plan", type: "json", required: false },
        { name: "worldcover_class", type: "number", required: false },
        { name: "worldcover_label", type: "text", required: false },
      ],
    });
    app.save(userPlots);
  },
  (app) => {
    for (const name of ["user_plots", "farms"]) {
      try {
        const col = app.findCollectionByNameOrId(name);
        app.delete(col);
      } catch (_) {}
    }
  }
);
