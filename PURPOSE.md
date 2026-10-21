This cell is the root cell for a project. It's primary purpose is to maintain a catalog of all cells related to this project and evaluate the creation of new cells. It also acts as a router for general new feature requests, redirecting them to an appropriate entry point.

All of the cells in this project can be listed using `c2j cells --json`.

To better understand what cells do, you can read their README.md, AGENTS.md and PURPOSE.md files and/or peruse their contents.

If you decide a new cell should be added, you can add it using the `add c2j cell add github.com/acme/auth --description '<3-4 sentence description>' command.
