/// <reference path="../pb_data/types.d.ts" />
migrate(
  (app) => {
    const userPlots = app.findCollectionByNameOrId("user_plots");
    if (!userPlots.fields.getByName("sub_plots")) {
      userPlots.fields.add(new JSONField({ name: "sub_plots", required: false }));
      app.save(userPlots);
    }
  },
  (app) => {
    try {
      const userPlots = app.findCollectionByNameOrId("user_plots");
      const field = userPlots.fields.getByName("sub_plots");
      if (field) {
        userPlots.fields.removeById(field.id);
        app.save(userPlots);
      }
    } catch (_) {}
  }
);
