import serverless_wsgi
# Importa o objeto 'app' Flask do seu arquivo principal (app.py)
# O caminho pode precisar de ajuste se sua estrutura de pastas for diferente
# Assumindo que api.py está em netlify/functions/ e app.py na raiz
import sys
import os

# Adiciona o diretório raiz ao path para encontrar app.py
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(root_dir)

try:
    from app import app
except ImportError as e:
    # Log de erro útil se a importação falhar
    print(f"Erro ao importar 'app' de app.py. Verifique sys.path e a estrutura do projeto.")
    print(f"Erro: {e}")
    # Define um app dummy para evitar falha completa na inicialização da função?
    # Ou simplesmente levanta o erro para que falhe claramente.
    raise

def handler(event, context):
    """Função handler que a Netlify/AWS Lambda irá chamar."""
    # Usa serverless_wsgi para traduzir o evento Lambda para WSGI
    return serverless_wsgi.handle_request(app, event, context) 