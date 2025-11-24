// app.js - updated to read Option A JSON layout
(async function () {
  try {
    const res = await fetch("../data/tree.json");
    const json = await res.json();

    // JSON layout: { people: {...}, families: {...}, tree: { chart: {...}, root: {...} } }
    const treantConfig = {
      chart: Object.assign({
        container: "#tree-container",
        rootOrientation: "NORTH",
        nodeAlign: "TOP",
        connectors: { type: "step" }
      }, json.tree && json.tree.chart ? json.tree.chart : {}),
      nodeStructure: json.tree ? json.tree.root : (json.root || {})
    };

    new Treant(treantConfig);

    // Optional: attach click handlers to nodes to show details using json.people[node.id]
    // You can use the 'id' property in nodes to map to json.people[id] for full data.
  } catch (err) {
    console.error("Failed to load tree JSON:", err);
    document.getElementById("tree-container").innerText = "Failed to load tree JSON. See console.";
  }
})();
