(() => {
  const open = () => new Promise((resolve, reject) => {
    const req = indexedDB.open("expense-tracker", 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore("meta");
      req.result.createObjectStore("queue", { keyPath: "client_id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  const run = async (store, mode, fn) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, mode);
      const request = fn(tx.objectStore(store));
      tx.oncomplete = () => resolve(request ? request.result : undefined);
      tx.onerror = () => reject(tx.error);
    });
  };
  window.OfflineDB = {
    getMeta: (key) => run("meta", "readonly", (s) => s.get(key)),
    setMeta: (key, value) => run("meta", "readwrite", (s) => s.put(value, key)),
    queueAll: () => run("queue", "readonly", (s) => s.getAll()),
    queuePut: (item) => run("queue", "readwrite", (s) => s.put(item)),
    queueDelete: (id) => run("queue", "readwrite", (s) => s.delete(id)),
  };
})();