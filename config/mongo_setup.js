/**
 * MongoDB Setup for NIHR + Innovate UK Grant Scrapers
 *
 * This script creates the shared grants collection and indexes.
 * Can be used by both NIHR and Innovate UK scrapers.
 *
 * Usage:
 *   mongosh "$MONGO_URI" < mongo_setup.js
 *
 * Or interactively:
 *   mongosh "$MONGO_URI"
 *   > load("mongo_setup.js")
 */

// Switch to the grants database
use ailsa_grants;

print("Setting up grants collection for NIHR + Innovate UK scrapers...\n");

// Create indexes for the grants collection
print("Creating indexes...");

// Primary unique index on grant_id
db.grants.createIndex(
    { "grant_id": 1 },
    { unique: true, name: "idx_grant_id_unique" }
);
print("  - Created unique index on grant_id");

// Source index for filtering by scraper source (nihr, innovate_uk)
db.grants.createIndex(
    { "source": 1 },
    { name: "idx_source" }
);
print("  - Created index on source");

// Compound index for common query: active grants by source
db.grants.createIndex(
    { "source": 1, "status": 1 },
    { name: "idx_source_status" }
);
print("  - Created compound index on source + status");

// Index for deadline-based queries
db.grants.createIndex(
    { "closes_at": 1 },
    { name: "idx_closes_at" }
);
print("  - Created index on closes_at");

// Compound index for finding active grants closing soon
db.grants.createIndex(
    { "status": 1, "closes_at": 1 },
    { name: "idx_status_closes_at" }
);
print("  - Created compound index on status + closes_at");

// Index for searching by external_id (reference number)
db.grants.createIndex(
    { "external_id": 1 },
    { name: "idx_external_id" }
);
print("  - Created index on external_id");

// Index for filtering by tags
db.grants.createIndex(
    { "tags": 1 },
    { name: "idx_tags" }
);
print("  - Created index on tags");

// Index for updated_at (for change tracking queries)
db.grants.createIndex(
    { "updated_at": -1 },
    { name: "idx_updated_at" }
);
print("  - Created index on updated_at");

// Text index for full-text search on title and description
db.grants.createIndex(
    { "title": "text", "description": "text" },
    { name: "idx_text_search", weights: { title: 10, description: 5 } }
);
print("  - Created text index on title + description");

print("\nIndexes created successfully!\n");

// Show collection stats
print("Collection stats:");
const stats = db.grants.stats();
print(`  - Document count: ${stats.count}`);
print(`  - Storage size: ${Math.round(stats.storageSize / 1024)} KB`);
print(`  - Index count: ${stats.nindexes}`);

// Show index list
print("\nIndexes:");
db.grants.getIndexes().forEach(idx => {
    print(`  - ${idx.name}: ${JSON.stringify(idx.key)}`);
});

print("\n========================================");
print("MongoDB setup complete!");
print("========================================");
print("\nThe grants collection is now ready for use by:");
print("  - NIHR scraper (source: 'nihr')");
print("  - Innovate UK scraper (source: 'innovate_uk')");
print("\nTest with:");
print("  db.grants.findOne({source: 'nihr'})");
print("  db.grants.countDocuments({source: 'nihr', status: 'active'})");
