Coolify manages Traefik for this stack.

This compose file is intentionally product-specific:

- it builds the runtime from the current repo;
- it mounts `citadl/bundle` into the backend and worker;
- it pins the public hostname to `citadl.gnosis.run`.

When Citadl moves into its own repo later, the bundle directory can stay the same and the build contexts can be swapped for pinned runtime images or tags.
