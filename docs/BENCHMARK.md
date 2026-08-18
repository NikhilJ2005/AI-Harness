# Benchmark results

- Specifications: **10**
- Passed every validation gate: **10/10** (100%)
- Average generation and validation time: **2.46s**
- Average files per project: **23.5**
- Average repair attempts: **0.00**
- Sandbox: subprocess (fast, no isolation)
- Self-healing: not exercised (no API key)

| Specification | Files | Validated | Repairs | Time (s) | Notes |
|---|---|---|---|---|---|
| `01_notes_api` | 17 | yes | 0 | 2.4 |  |
| `02_blog_api` | 25 | yes | 0 | 2.47 |  |
| `03_shop_api` | 28 | yes | 0 | 2.52 |  |
| `04_library_api` | 25 | yes | 0 | 2.6 |  |
| `05_forum_api` | 25 | yes | 0 | 2.57 |  |
| `06_crm_api` | 23 | yes | 0 | 2.42 |  |
| `07_fitness_api_plain_password` | 22 | yes | 0 | 2.33 |  |
| `08_event_api_missing_key` | 25 | yes | 0 | 2.47 |  |
| `09_recipe_api_many_to_many` | 25 | yes | 0 | 2.4 |  |
| `10_inventory_api` | 20 | yes | 0 | 2.37 |  |

## Specification repairs

Problems the planner found and fixed before generating, each
recorded in the change ledger:

- `02_blog_api`: Added 'password_hash' to User to store passwords.
- `03_shop_api`: Treated Customer as the account entity for authentication, because it carries a login field.
- `03_shop_api`: Added 'password_hash' to Customer to store passwords.
- `04_library_api`: Added 'password_hash' to Member to store passwords.
- `05_forum_api`: Added 'password_hash' to ForumUser to store passwords.
- `07_fitness_api_plain_password`: Replaced the plain 'password' field on User with 'password_hash' so passwords are never stored in clear text.
- `07_fitness_api_plain_password`: Added 'password_hash' to User to store passwords.
- `08_event_api_missing_key`: Added an 'id' primary key to Ticket.
- `08_event_api_missing_key`: Treated Attendee as the account entity for authentication, because it carries a login field.
- `08_event_api_missing_key`: Added 'password_hash' to Attendee to store passwords.
- `09_recipe_api_many_to_many`: Skipped a many-to-many relationship between Recipe and Ingredient: association tables are not supported yet.
- `09_recipe_api_many_to_many`: Treated Chef as the account entity for authentication, because it carries a login field.
- `09_recipe_api_many_to_many`: Added 'password_hash' to Chef to store passwords.
