PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('admin','sales','finance','manager')),
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS customers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  contact    TEXT DEFAULT '',
  phone      TEXT DEFAULT '',
  address    TEXT DEFAULT '',
  industry   TEXT DEFAULT '',
  level      TEXT NOT NULL DEFAULT 'B' CHECK(level IN ('A','B','C')),
  owner_id   INTEGER REFERENCES users(id),
  remark     TEXT DEFAULT '',
  credit_limit REAL NOT NULL DEFAULT 0 CHECK(credit_limit >= 0),
  credit_hold INTEGER NOT NULL DEFAULT 0,
  is_demo    INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS followups (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  content     TEXT NOT NULL,
  next_date   TEXT DEFAULT '',
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS contracts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_no   TEXT NOT NULL UNIQUE,
  customer_id   INTEGER NOT NULL REFERENCES customers(id),
  title         TEXT NOT NULL,
  type          TEXT NOT NULL DEFAULT 'product',
  amount        REAL NOT NULL DEFAULT 0,
  sign_date     TEXT DEFAULT '',
  delivery_date TEXT DEFAULT '',
  status        TEXT NOT NULL DEFAULT '已签',
  owner_id      INTEGER REFERENCES users(id),
  remark        TEXT DEFAULT '',
  attachment    TEXT DEFAULT '',
  is_demo       INTEGER NOT NULL DEFAULT 0,
  created_by    INTEGER REFERENCES users(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS contract_files (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  filename    TEXT NOT NULL,
  orig_name   TEXT NOT NULL,
  size        INTEGER NOT NULL DEFAULT 0,
  uploaded_by INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS shipments (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  shipment_no      TEXT NOT NULL UNIQUE,
  type             TEXT NOT NULL CHECK(type IN ('contract','temp')),
  contract_id      INTEGER REFERENCES contracts(id),
  batch_id         INTEGER REFERENCES material_batches(id),
  customer_id      INTEGER NOT NULL REFERENCES customers(id),
  ship_date        TEXT NOT NULL,
  from_address     TEXT DEFAULT '',
  to_address       TEXT DEFAULT '',
  transport_method TEXT DEFAULT '',
  transport_fee    REAL NOT NULL DEFAULT 0,
  remark           TEXT DEFAULT '',
  is_demo          INTEGER NOT NULL DEFAULT 0,
  created_by       INTEGER REFERENCES users(id),
  created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS shipment_items (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  shipment_id      INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  contract_item_id INTEGER REFERENCES contract_items(id) ON DELETE SET NULL,
  name             TEXT NOT NULL,
  spec             TEXT DEFAULT '',
  unit             TEXT DEFAULT '',
  quantity         REAL NOT NULL DEFAULT 1,
  unit_price       REAL NOT NULL DEFAULT 0,
  amount           REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dict_types (
  code    TEXT PRIMARY KEY,
  name    TEXT NOT NULL,
  builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dict_items (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  type_code TEXT NOT NULL REFERENCES dict_types(code) ON DELETE CASCADE,
  label     TEXT NOT NULL,
  sort      INTEGER NOT NULL DEFAULT 0,
  active    INTEGER NOT NULL DEFAULT 1,
  UNIQUE(type_code, label)
);

CREATE TABLE IF NOT EXISTS payment_plans (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  seq         INTEGER NOT NULL DEFAULT 1,
  name        TEXT NOT NULL,
  ratio       REAL NOT NULL DEFAULT 0,
  amount      REAL NOT NULL DEFAULT 0,
  due_date    TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS payments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id     INTEGER REFERENCES payment_plans(id) ON DELETE SET NULL,
  contract_id INTEGER NOT NULL REFERENCES contracts(id),
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  amount      REAL NOT NULL CHECK(amount > 0),
  pay_date    TEXT NOT NULL,
  method      TEXT DEFAULT '',
  remark      TEXT DEFAULT '',
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS payment_allocations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id  INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
  plan_id     INTEGER NOT NULL REFERENCES payment_plans(id),
  amount      REAL NOT NULL CHECK(amount > 0),
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS invoices (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id  INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  invoice_no   TEXT NOT NULL,
  type         TEXT NOT NULL DEFAULT '增值税普通发票',
  amount       REAL NOT NULL,
  invoice_date TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT '已开' CHECK(status IN ('已开','作废','红冲')),
  red_invoice_of INTEGER REFERENCES invoices(id),
  remark       TEXT DEFAULT '',
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS products (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  model      TEXT DEFAULT '',
  spec       TEXT DEFAULT '',
  unit       TEXT DEFAULT '台',
  price      REAL NOT NULL DEFAULT 0 CHECK(price >= 0),
  category   TEXT DEFAULT '',
  remark     TEXT DEFAULT '',
  active     INTEGER NOT NULL DEFAULT 1,
  is_demo    INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS services (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  type       TEXT DEFAULT '',
  content    TEXT DEFAULT '',
  unit       TEXT DEFAULT '次',
  price      REAL NOT NULL DEFAULT 0 CHECK(price >= 0),
  remark     TEXT DEFAULT '',
  active     INTEGER NOT NULL DEFAULT 1,
  is_demo    INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS contract_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  item_type   TEXT NOT NULL CHECK(item_type IN ('product','service','other')),
  ref_id      INTEGER,
  name        TEXT NOT NULL,
  spec        TEXT DEFAULT '',
  quantity    REAL NOT NULL DEFAULT 1,
  unit        TEXT DEFAULT '',
  unit_price  REAL NOT NULL DEFAULT 0,
  amount      REAL NOT NULL DEFAULT 0,
  remark      TEXT DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS material_batches (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_no          TEXT NOT NULL UNIQUE,
  contract_id       INTEGER NOT NULL REFERENCES contracts(id),
  customer_id       INTEGER NOT NULL REFERENCES customers(id),
  received_date     TEXT NOT NULL,
  item_name         TEXT NOT NULL,
  drawing_no        TEXT DEFAULT '',
  drawing_revision  TEXT DEFAULT '',
  material          TEXT DEFAULT '',
  received_qty      REAL NOT NULL CHECK(received_qty > 0),
  unit              TEXT DEFAULT '件',
  surface_condition TEXT DEFAULT '',
  status            TEXT NOT NULL DEFAULT '待排产',
  remark            TEXT DEFAULT '',
  is_demo           INTEGER NOT NULL DEFAULT 0,
  created_by        INTEGER REFERENCES users(id),
  created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS furnace_batches (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  furnace_no   TEXT NOT NULL UNIQUE,
  batch_id     INTEGER NOT NULL REFERENCES material_batches(id),
  contract_id  INTEGER NOT NULL REFERENCES contracts(id),
  process      TEXT NOT NULL,
  recipe       TEXT DEFAULT '',
  equipment    TEXT DEFAULT '',
  operator_name TEXT DEFAULT '',
  quantity     REAL NOT NULL CHECK(quantity > 0),
  started_at   TEXT DEFAULT '',
  finished_at  TEXT DEFAULT '',
  status       TEXT NOT NULL DEFAULT '加工中',
  remark       TEXT DEFAULT '',
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS quality_inspections (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  furnace_batch_id  INTEGER NOT NULL REFERENCES furnace_batches(id),
  batch_id          INTEGER NOT NULL REFERENCES material_batches(id),
  contract_id       INTEGER NOT NULL REFERENCES contracts(id),
  inspection_date   TEXT NOT NULL,
  inspector_name    TEXT DEFAULT '',
  inspected_qty     REAL NOT NULL CHECK(inspected_qty > 0),
  pass_qty          REAL NOT NULL CHECK(pass_qty >= 0),
  fail_qty          REAL NOT NULL CHECK(fail_qty >= 0),
  adhesion          TEXT DEFAULT '',
  film_thickness    TEXT DEFAULT '',
  salt_spray_hours  REAL,
  result            TEXT NOT NULL CHECK(result IN ('合格','不合格','让步接收')),
  report_name       TEXT DEFAULT '',
  remark            TEXT DEFAULT '',
  created_by        INTEGER REFERENCES users(id),
  created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS acceptance_records (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  record_no    TEXT NOT NULL UNIQUE,
  record_type  TEXT NOT NULL CHECK(record_type IN ('签收','验收')),
  contract_id  INTEGER NOT NULL REFERENCES contracts(id),
  shipment_id  INTEGER REFERENCES shipments(id),
  batch_id     INTEGER REFERENCES material_batches(id),
  record_date  TEXT NOT NULL,
  quantity     REAL NOT NULL CHECK(quantity > 0),
  result       TEXT NOT NULL,
  signed_by    TEXT DEFAULT '',
  proof_name   TEXT DEFAULT '',
  remark       TEXT DEFAULT '',
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS reconciliations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  statement_no  TEXT NOT NULL UNIQUE,
  contract_id   INTEGER NOT NULL REFERENCES contracts(id),
  period_start  TEXT NOT NULL,
  period_end    TEXT NOT NULL,
  amount        REAL NOT NULL CHECK(amount > 0),
  status        TEXT NOT NULL DEFAULT '待确认' CHECK(status IN ('待确认','已确认','异议')),
  confirmed_by  TEXT DEFAULT '',
  confirmed_at  TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_by    INTEGER REFERENCES users(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS cost_entries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id  INTEGER NOT NULL REFERENCES contracts(id),
  batch_id     INTEGER REFERENCES material_batches(id),
  furnace_batch_id INTEGER REFERENCES furnace_batches(id),
  cost_date    TEXT NOT NULL,
  category     TEXT NOT NULL,
  amount       REAL NOT NULL CHECK(amount > 0),
  supplier     TEXT DEFAULT '',
  remark       TEXT DEFAULT '',
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS equipment (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  code                  TEXT NOT NULL UNIQUE,
  name                  TEXT NOT NULL,
  daily_available_hours REAL NOT NULL DEFAULT 16 CHECK(daily_available_hours > 0),
  active                INTEGER NOT NULL DEFAULT 1,
  is_demo               INTEGER NOT NULL DEFAULT 0,
  remark                TEXT DEFAULT '',
  created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS document_counters (
  key         TEXT PRIMARY KEY,
  value       INTEGER NOT NULL DEFAULT 0 CHECK(value >= 0)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL,
  entity_id   INTEGER NOT NULL,
  action      TEXT NOT NULL,
  before_json TEXT DEFAULT '',
  after_json  TEXT DEFAULT '',
  reason      TEXT DEFAULT '',
  actor_id    INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS contract_changes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id   INTEGER NOT NULL REFERENCES contracts(id),
  before_amount REAL NOT NULL,
  after_amount  REAL NOT NULL,
  before_json   TEXT NOT NULL,
  after_json    TEXT NOT NULL,
  reason        TEXT NOT NULL,
  created_by    INTEGER REFERENCES users(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_changes_contract ON contract_changes(contract_id);
CREATE INDEX IF NOT EXISTS idx_cost_contract ON cost_entries(contract_id);
CREATE INDEX IF NOT EXISTS idx_cost_date ON cost_entries(cost_date);
CREATE INDEX IF NOT EXISTS idx_material_contract ON material_batches(contract_id);
CREATE INDEX IF NOT EXISTS idx_material_customer ON material_batches(customer_id);
CREATE INDEX IF NOT EXISTS idx_furnace_batch ON furnace_batches(batch_id);
CREATE INDEX IF NOT EXISTS idx_furnace_contract ON furnace_batches(contract_id);
CREATE INDEX IF NOT EXISTS idx_quality_furnace ON quality_inspections(furnace_batch_id);
CREATE INDEX IF NOT EXISTS idx_quality_batch ON quality_inspections(batch_id);
CREATE INDEX IF NOT EXISTS idx_items_contract ON contract_items(contract_id);
CREATE INDEX IF NOT EXISTS idx_items_ref      ON contract_items(item_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_files_contract   ON contract_files(contract_id);
CREATE INDEX IF NOT EXISTS idx_ship_contract    ON shipments(contract_id);
CREATE INDEX IF NOT EXISTS idx_shipitems_ship   ON shipment_items(shipment_id);
CREATE INDEX IF NOT EXISTS idx_shipitems_item   ON shipment_items(contract_item_id);
CREATE INDEX IF NOT EXISTS idx_dictitems_type   ON dict_items(type_code);
CREATE INDEX IF NOT EXISTS idx_customers_owner   ON customers(owner_id);
CREATE INDEX IF NOT EXISTS idx_contracts_customer ON contracts(customer_id);
CREATE INDEX IF NOT EXISTS idx_contracts_owner    ON contracts(owner_id);
CREATE INDEX IF NOT EXISTS idx_plans_contract     ON payment_plans(contract_id);
CREATE INDEX IF NOT EXISTS idx_plans_due          ON payment_plans(due_date);
CREATE INDEX IF NOT EXISTS idx_payments_contract  ON payments(contract_id);
CREATE INDEX IF NOT EXISTS idx_payments_plan      ON payments(plan_id);
CREATE INDEX IF NOT EXISTS idx_invoices_contract  ON invoices(contract_id);
