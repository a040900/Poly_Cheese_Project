module.exports = {
  apps: [{
    name: 'cheesedog',
    script: 'app/main.py',
    interpreter: '/root/.openclaw/workspace/Poly_Cheese_Project/venv/bin/python',
    cwd: '/root/.openclaw/workspace/Poly_Cheese_Project/backend',
    env: {
      PYTHONPATH: '/root/.openclaw/workspace/Poly_Cheese_Project/backend'
    }
  }]
}
