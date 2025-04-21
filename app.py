from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from datetime import datetime, timedelta, date
import os
from dotenv import load_dotenv # Carrega variáveis de ambiente
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import requests
import math
from sqlalchemy import func # Para usar funções SQL como SUM, MAX, MIN
import click

# Carrega variáveis de ambiente do arquivo .env (se existir)
# Ótimo para desenvolvimento local
load_dotenv()

app = Flask(__name__)

# --- Configuração do App ---
# Lê SECRET_KEY da variável de ambiente. Fornece um default inseguro APENAS para dev.
# IMPORTANTE: Defina SECRET_KEY no seu ambiente de produção!
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-insecure-change-me')

# Lê DATABASE_URL da variável de ambiente. Define um default para SQLite local.
# A pasta 'instance' será criada automaticamente pelo Flask se não existir.
default_db_url = 'sqlite:///' + os.path.join(app.instance_path, 'app.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', default_db_url)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Desativa warnings desnecessários

# Configurações de Sessão Permanente (mantido)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

# --- Inicialização das Extensões ---
db = SQLAlchemy(app)
migrate = Migrate(app, db) # Inicializa o Flask-Migrate
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Nome da view de login

# --- Modelos do Banco de Dados (SQLAlchemy) ---

class User(UserMixin, db.Model):
    id = db.Column(db.String(50), primary_key=True) # Usando String como ID, pode ser db.Integer se preferir auto-increment
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

class Trade(db.Model):
    id = db.Column(db.String(50), primary_key=True) # ID baseado em timestamp original
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at_timestamp = db.Column(db.DateTime, nullable=True, index=True) # Timestamp de fechamento
    symbol = db.Column(db.String(20), nullable=False, index=True)
    side = db.Column(db.String(10), nullable=True) # long/short
    size = db.Column(db.Float, nullable=True)
    entry_price = db.Column(db.Float, nullable=True)
    exit_price = db.Column(db.Float, nullable=True)
    pnl = db.Column(db.Float, nullable=True)
    take_profit = db.Column(db.Float, nullable=True)
    stop_loss = db.Column(db.Float, nullable=True)
    tier = db.Column(db.String(10), nullable=True) # TIER usado no trade
    calculated_fee = db.Column(db.Float, nullable=True, default=0.0) # Taxa calculada
    volume_contribution = db.Column(db.Float, nullable=True, default=0.0) # Contribuição ao volume

    def to_dict(self):
        """ Helper para converter Trade em dicionário serializável. """
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'closed_at_timestamp': self.closed_at_timestamp.isoformat() if self.closed_at_timestamp else None,
            'symbol': self.symbol,
            'side': self.side,
            'size': self.size,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'pnl': self.pnl,
            'take_profit': self.take_profit,
            'stop_loss': self.stop_loss,
            'tier': self.tier,
            'calculated_fee': self.calculated_fee,
            'volume_contribution': self.volume_contribution
        }

class Balance(db.Model):
    # id = db.Column(db.Integer, primary_key=True) # ID Auto-incrementável é opcional aqui
    symbol = db.Column(db.String(20), primary_key=True, nullable=False, index=True) # Usar symbol como PK é mais direto
    amount = db.Column(db.Float, nullable=False, default=0.0)

class ConfigValue(db.Model):
    """ Modelo genérico para armazenar valores de configuração, como total_volume """
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=True) # Armazena como string, converte ao usar

# --- User Loader (Flask-Login) ---
@login_manager.user_loader
def load_user(user_id):
    # Busca o usuário pelo ID no banco de dados
    return db.session.get(User, user_id)

# --- COMENTADO: User Model and Storage antigo (In-memory) ---
# class User(UserMixin):
#     def __init__(self, id, email, password_hash):
#         self.id = id
#         self.email = email
#         self.password_hash = password_hash
# hashed_password = generate_password_hash('62845_Madhouse', method='pbkdf2:sha256')
# users = {
#     '1': User(id='1', email='leonardo_guimaraes@hotmail.com', password_hash=hashed_password)
# }
# @login_manager.user_loader
# def load_user(user_id):
#     return users.get(user_id)
# ----------------------------------------------------------

# --- COMENTADO: File Handling antigo (JSON) ---
# TRADES_FILE = 'backpack_trades.json'
# VOLUME_FILE = 'volume_data.json'
# BALANCES_FILE = 'balances.json'
# def load_trades(): ...
# def save_trades(trades): ...
# def load_total_volume(): ...
# def save_total_volume(volume): ...
# def load_balances(): ...
# def save_balances(balances): ...
# ---------------------------------------------

# --- Constantes (Mantidas) ---
# (TIER_FEES_MAKER, TIER_FEES_TAKER, DEFAULTS)
TIER_FEES_MAKER = {
    '1': 0.00050, '2': 0.00045, '3': 0.00040, '4': 0.00035, '5': 0.00030,
    '6': 0.00028, 'VIP1': 0.00026, 'VIP2': 0.00024, 'VIP3': 0.00022,
    'VIP4': 0.00020, 'VIP5': 0.00018,
}
TIER_FEES_TAKER = {
    '1': 0.00050, '2': 0.00045, '3': 0.00040, '4': 0.00035, '5': 0.00030,
    '6': 0.00028, 'VIP1': 0.00026, 'VIP2': 0.00024, 'VIP3': 0.00022,
    'VIP4': 0.00020, 'VIP5': 0.00018,
}
DEFAULT_TIER = '1'
DEFAULT_MAKER_FEE_RATE = TIER_FEES_MAKER[DEFAULT_TIER]
DEFAULT_TAKER_FEE_RATE = TIER_FEES_TAKER[DEFAULT_TIER]
# Mapeamento Símbolo -> ID API CoinGecko (Mantido)
symbol_to_id_map = {
    'btc': 'bitcoin', 'eth': 'ethereum', 'bnb': 'binancecoin', 'xrp': 'ripple',
    'sol': 'solana', 's': 'sonic-3', 'hype': 'hyperliquid', 'sui': 'sui',
    'link': 'chainlink', 'jup': 'jupiter-exchange-solana', 'bera': 'berachain-bera',
    'doge': 'dogecoin', 'trump': 'official-trump', 'avax': 'avalanche-2',
    'ena': 'ethena', 'arb': 'arbitrum', 'wif': 'dogwifcoin', 'ltc': 'litecoin',
    'ondo': 'ondo-finance', 'dot': 'polkadot', 'ada': 'cardano', 'kaito': 'kaito',
    'aave': 'aave', 'fartcoin': 'fartcoin', 'ip': 'story-2', 'kmno': 'kamino',
    'usdt': 'tether', 'bonk': 'bonk', 'usdc': 'usd-coin'
}

# --- Helper Functions ---
def get_total_volume_from_db():
    """ Busca o valor de 'total_volume' do banco de dados (tabela ConfigValue). """
    config = db.session.get(ConfigValue, 'total_volume')
    if config and config.value:
        try:
            return float(config.value)
        except (ValueError, TypeError):
            print(f"[WARN] Valor inválido para total_volume no DB: {config.value}")
            return 0.0
    # Se a chave não existe, inicializa no DB e retorna 0
    print("[INFO] Chave 'total_volume' não encontrada no DB, inicializando com 0.0")
    save_total_volume_to_db(0.0)
    return 0.0

def save_total_volume_to_db(volume):
    """ Salva/Atualiza o valor de 'total_volume' no banco de dados (tabela ConfigValue). """
    config = db.session.get(ConfigValue, 'total_volume')
    if config:
        config.value = str(volume)
    else:
        config = ConfigValue(key='total_volume', value=str(volume))
        db.session.add(config)
    # O commit será feito pela função que chama esta helper

def is_today(dt_object):
    """Verifica se um objeto datetime representa a data de hoje."""
    if not isinstance(dt_object, datetime):
        return False
    try:
        return dt_object.date() == date.today()
    except Exception as e:
        print(f"[is_today ERROR] Erro inesperado ao processar datetime {dt_object}: {e}")
        return False

def parse_datetime_safe(timestamp_str):
    """ Converte string ISO para datetime UTC, retornando None em caso de erro. """
    if not timestamp_str or not isinstance(timestamp_str, str):
        return None
    try:
        # Remove 'Z' e outros offsets comuns para tratar como UTC
        # Tenta lidar com precisão variável de frações de segundo
        if 'Z' in timestamp_str:
            ts = timestamp_str.replace('Z', '')
        elif '+' in timestamp_str:
             ts = timestamp_str.split('+')[0]
        else:
             ts = timestamp_str
        
        if '.' in ts:
             ts_main, ts_frac = ts.split('.', 1)
             # Trunca fração para 6 dígitos (microsegundos)
             ts_frac = ts_frac[:6]
             ts = f"{ts_main}.{ts_frac}"
             dt = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f')
        else:
             dt = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S')
        return dt # Retorna como UTC implícito
    except (ValueError, TypeError) as e:
        print(f"[parse_datetime_safe WARN] Formato de timestamp inválido: {timestamp_str}, Erro: {e}")
        return None

# --- Funções de Cálculo (Reutilizadas/Adaptadas) ---

def calculate_trade_fee(trade_data):
    """Calcula a taxa (maker/taker) para um trade baseado nos dados fornecidos."""
    # Garantir que trade_data seja um dicionário
    if not isinstance(trade_data, dict):
        print("[Fee Calc WARN] trade_data não é um dicionário.")
        return 0.0
        
    calculated_trade_fee = 0.0
    try:
        selected_tier = str(trade_data.get('tier', DEFAULT_TIER))
        maker_fee_rate = TIER_FEES_MAKER.get(selected_tier, DEFAULT_MAKER_FEE_RATE)
        taker_fee_rate = TIER_FEES_TAKER.get(selected_tier, DEFAULT_TAKER_FEE_RATE)

        # Tenta converter para float, retorna 0.0 em erro
        def safe_float(value, default=None):
             if value is None: return default
             try:
                 f_val = float(value)
                 return f_val if not math.isnan(f_val) else default
             except (ValueError, TypeError):
                 return default

        entry_price = safe_float(trade_data.get('entry_price'))
        exit_price = safe_float(trade_data.get('exit_price'))
        size = safe_float(trade_data.get('size'))

        # Só calcula se os valores necessários são válidos
        if entry_price is None or size is None:
            print("[Fee Calc WARN] Entry price ou size inválido/ausente.")
            return 0.0 # Não pode calcular taxa de entrada

        # Taxa de Entrada (Maker)
        entry_value = abs(entry_price * size)
        calculated_trade_fee += entry_value * maker_fee_rate

        # Taxa de Saída (Taker - se fechado)
        if exit_price is not None: # Verifica se tem preço de saída válido
            exit_value = abs(exit_price * size)
            calculated_trade_fee += exit_value * taker_fee_rate

        return round(calculated_trade_fee, 4)

    except Exception as e:
        print(f"[Fee Calculation ERROR] Erro ao calcular taxa: {e}")
        import traceback
        traceback.print_exc()
        return 0.0

def calculate_volume_contribution(trade_data):
    """Calcula a contribuição de volume (entry_price * size * 2) para um trade."""
    # Garantir que trade_data seja um dicionário
    if not isinstance(trade_data, dict):
        print("[Volume Calc WARN] trade_data não é um dicionário.")
        return 0.0
        
    volume_contribution = 0.0
    try:
        # Tenta converter para float, retorna 0.0 em erro
        def safe_float(value, default=None):
             if value is None: return default
             try:
                 f_val = float(value)
                 return f_val if not math.isnan(f_val) else default
             except (ValueError, TypeError):
                 return default
                 
        entry_price = safe_float(trade_data.get('entry_price'))
        size = safe_float(trade_data.get('size'))

        if entry_price is not None and size is not None:
            volume_contribution = abs(entry_price * size * 2)
            return round(volume_contribution, 4)
        else:
            print("[Volume Calc WARN] Entry price ou size inválido/ausente para cálculo.")
            return 0.0
    except Exception as e:
        print(f"[Volume Contribution ERROR] Erro ao calcular contribuição: {e}")
        import traceback
        traceback.print_exc()
        return 0.0

# --- Rotas Flask ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Busca usuário pelo email no BD
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            return redirect(url_for('index'))
        else:
            flash('E-mail ou senha inválidos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/cryptocurrencies')
@login_required
def cryptocurrencies():
    return render_template('cryptocurrencies.html')

# Rota para obter posições abertas (query no DB)
@app.route('/api/positions', methods=['GET'])
@login_required
def get_open_positions():
    try:
        open_positions_db = Trade.query.filter(
            Trade.entry_price.isnot(None),
            Trade.size.isnot(None),
            Trade.size != 0,
            Trade.exit_price.is_(None) # Verifica se exit_price é NULL
        ).order_by(Trade.timestamp.desc()).all()

        # Converte objetos SQLAlchemy para dicionários JSON serializáveis
        open_positions_json = [pos.to_dict() for pos in open_positions_db]
        return jsonify(open_positions_json)
    except Exception as e:
        print(f"[API /api/positions ERROR] {e}")
        return jsonify({"error": "Erro ao buscar posições abertas"}), 500

# Rota para obter o volume total acumulado (lê do DB)
@app.route('/api/total_volume', methods=['GET'])
@login_required
def get_total_volume():
    try:
        volume = get_total_volume_from_db()
        return jsonify({'total_volume': volume})
    except Exception as e:
        print(f"[API /api/total_volume ERROR] {e}")
        return jsonify({"error": "Erro ao buscar volume total"}), 500

@app.route('/api/trades', methods=['GET', 'POST'])
@login_required
def handle_trades():
    if request.method == 'GET':
        # GET: Retorna trades FECHADOS do Histórico
        try:
            closed_trades_db = Trade.query.filter(
                Trade.exit_price.isnot(None)
            ).order_by(Trade.timestamp.desc()).all()

            # Usa o helper to_dict() do modelo
            closed_trades_json = [trade.to_dict() for trade in closed_trades_db]
            return jsonify(closed_trades_json)
        except Exception as e:
             print(f"[API /api/trades GET ERROR] {e}")
             return jsonify({"error": "Erro ao buscar histórico de trades"}), 500

    elif request.method == 'POST':
        # POST: Adiciona um novo trade
        try:
            data = request.json
            if not data or 'symbol' not in data: # PnL não é obrigatório na criação inicial
                return jsonify({'error': 'Dados inválidos (símbolo obrigatório)'}), 400

            # --- Preparação dos dados para o novo trade ---
            trade_id = str(datetime.now().timestamp()) # Gera ID único
            now_dt = datetime.utcnow() # Usar UTC para consistência no DB

            # Converte campos numéricos, tratando NaN e vazios como None
            parsed_data = {}
            for field in ['pnl', 'entry_price', 'exit_price', 'size', 'take_profit', 'stop_loss']:
                value = data.get(field)
                if value is not None and value != '':
                    try:
                        float_value = float(value)
                        parsed_data[field] = None if math.isnan(float_value) else float_value
                    except (ValueError, TypeError):
                        print(f"[ADD TRADE WARN] Valor inválido para '{field}': {value}. Ignorando.")
                        parsed_data[field] = None
                else:
                    parsed_data[field] = None

            # Usa os dados parseados para calcular taxa e volume
            fee_calc_data = parsed_data.copy()
            fee_calc_data['tier'] = data.get('tier', DEFAULT_TIER)
            calculated_fee = calculate_trade_fee(fee_calc_data)
            volume_contribution = calculate_volume_contribution(fee_calc_data) # Baseado na entrada

            # Cria nova instância do Trade
            new_trade = Trade(
                id=trade_id,
                timestamp=now_dt,
                symbol=data.get('symbol', 'UNKNOWN').upper(), # Garante caixa alta
                side=data.get('side'),
                size=parsed_data.get('size'),
                entry_price=parsed_data.get('entry_price'),
                exit_price=parsed_data.get('exit_price'), # Pode ser None se aberto
                pnl=parsed_data.get('pnl'),             # Pode ser None se aberto
                take_profit=parsed_data.get('take_profit'),
                stop_loss=parsed_data.get('stop_loss'),
                tier=fee_calc_data['tier'], # Usa o tier que foi para o cálculo da taxa
                calculated_fee=calculated_fee,
                volume_contribution=volume_contribution
                # closed_at_timestamp será definido abaixo se necessário
            )

            # Define closed_at_timestamp se o trade já está sendo adicionado como fechado
            if new_trade.exit_price is not None:
                 new_trade.closed_at_timestamp = now_dt

            # Adiciona ao banco de dados
            db.session.add(new_trade)
            # Precisa commitar antes de ler o volume para evitar problemas com save_total_volume_to_db
            # db.session.flush() # Garante que new_trade tenha acesso à sessão se necessário

            # Atualiza o volume total
            current_total_volume = get_total_volume_from_db()
            updated_total_volume = current_total_volume + (volume_contribution or 0.0)
            save_total_volume_to_db(updated_total_volume) # Esta função adiciona/atualiza e faz parte do commit

            db.session.commit() # Commita o trade E a atualização do volume
            print(f"[ADD TRADE DB] Trade adicionado com ID: {new_trade.id}")

            # Retorna o trade adicionado usando to_dict()
            return jsonify(new_trade.to_dict()), 201

        except Exception as e:
            db.session.rollback() # Desfaz mudanças em caso de erro
            print(f"[API /api/trades POST ERROR] Erro ao adicionar trade: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Erro interno ao adicionar trade: {str(e)}'}), 500

@app.route('/api/trades/<trade_id>', methods=['GET', 'DELETE', 'PUT'])
@login_required
def handle_trade(trade_id):
    # Busca o trade pelo ID no BD
    # Usar with_for_update() pode ser útil se houver muita concorrência, mas complica
    trade = db.session.get(Trade, trade_id)

    if not trade:
        return jsonify({'error': 'Trade não encontrado'}), 404

    if request.method == 'GET':
        # Retorna os dados do trade específico usando to_dict()
        return jsonify(trade.to_dict()), 200

    elif request.method == 'DELETE':
        try:
            print(f"[DELETE TRADE DB] Recebido pedido para deletar trade ID: {trade_id}")
            volume_to_subtract = trade.volume_contribution or 0.0
            symbol = trade.symbol # Guarda para log

            # Deleta o trade
            db.session.delete(trade)

            # Subtrai a contribuição do volume total
            current_total_volume = get_total_volume_from_db()
            updated_total_volume = current_total_volume - volume_to_subtract
            save_total_volume_to_db(updated_total_volume)

            db.session.commit() # Commita delete E atualização do volume
            print(f"[DELETE TRADE DB] Trade {trade_id} ({symbol}) deletado. Volume subtraído: {volume_to_subtract}")
            return jsonify({'message': 'Trade deletado com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            print(f"[API /api/trades DELETE ERROR] Erro ao deletar trade {trade_id}: {e}")
            return jsonify({'error': f'Erro interno ao deletar trade: {str(e)}'}), 500

    elif request.method == 'PUT':
        try:
            data = request.json
            print(f"[PUT TRADE DB {trade_id}] Dados recebidos: {data}")

            # Guarda estado antigo para comparação
            old_exit_price = trade.exit_price
            is_currently_open = old_exit_price is None
            old_volume_contribution = trade.volume_contribution or 0.0

            # Atualiza campos simples
            if 'symbol' in data: trade.symbol = data['symbol'].upper()
            if 'side' in data: trade.side = data['side']
            # Assume que TIER não muda após criação, mas poderia ser adicionado aqui

            # Atualiza campos numéricos (incluindo TP/SL)
            # Usar um loop para tratar None/NaN
            updated_numeric_fields = False
            for field in ['pnl', 'entry_price', 'exit_price', 'size', 'take_profit', 'stop_loss']:
                if field in data:
                    original_value = getattr(trade, field)
                    value = data[field]
                    new_value = None
                    if value is not None and value != '':
                        try:
                            float_value = float(value)
                            if not math.isnan(float_value):
                                new_value = float_value
                        except (ValueError, TypeError):
                            print(f"[PUT WARN {trade_id}] Valor inválido para '{field}': {value}. Definindo como None.")
                            new_value = None # Garante None em caso de erro
                    
                    # Define o atributo apenas se o valor mudou
                    if new_value != original_value:
                         setattr(trade, field, new_value)
                         updated_numeric_fields = True # Marca que algo mudou
                         print(f"[PUT TRADE DB {trade_id}] Campo '{field}' atualizado para: {new_value}")


            # Lógica de Fechamento/Reabertura e Timestamps
            new_exit_price = trade.exit_price # Pega valor possivelmente atualizado
            is_closing_now = is_currently_open and (new_exit_price is not None)
            is_reopening_now = (not is_currently_open) and (new_exit_price is None)

            if is_closing_now:
                 trade.closed_at_timestamp = datetime.utcnow()
                 print(f"[PUT TRADE DB {trade_id}] Trade sendo fechado. Definindo closed_at_timestamp.")
                 # PnL deve ter sido fornecido ou calculado no frontend/API
                 if trade.pnl is None:
                      print(f"[PUT WARN {trade_id}] Fechando trade sem PnL definido!")
            elif is_reopening_now:
                 trade.closed_at_timestamp = None
                 trade.exit_price = None # Garante que está None
                 trade.pnl = None # PnL não realizado de novo
                 print(f"[PUT TRADE DB {trade_id}] Trade sendo reaberto. Removendo closed_at_timestamp, exit_price, pnl.")

            # Recalcular taxa SEMPRE que houver atualização numérica relevante (size, entry, exit)
            # if updated_numeric_fields: # Ou recalcular sempre para garantir?
            trade_data_for_fee = trade.to_dict() # Usa helper para pegar dados atuais
            trade.calculated_fee = calculate_trade_fee(trade_data_for_fee)
            print(f"[PUT TRADE DB {trade_id}] Taxa recalculada: {trade.calculated_fee}")

            # Se entry_price ou size mudou, recalcula contribuição e ajusta total
            if hasattr(trade, 'entry_price') or hasattr(trade, 'size'): # Verifica se os atributos foram atualizados
                 trade_data_for_vol = trade.to_dict()
                 new_volume_contribution = calculate_volume_contribution(trade_data_for_vol)
                 volume_diff = (new_volume_contribution or 0.0) - old_volume_contribution
                 if volume_diff != 0:
                    trade.volume_contribution = new_volume_contribution
                    current_total_volume = get_total_volume_from_db()
                    save_total_volume_to_db(current_total_volume + volume_diff)
                    print(f"[PUT TRADE DB {trade_id}] Volume contribution recalculado para {new_volume_contribution}. Total ajustado por {volume_diff}.")


            db.session.commit() # Commita todas as alterações
            print(f"[PUT TRADE DB {trade_id}] Trade atualizado com sucesso.")
            return jsonify(trade.to_dict()), 200 # Retorna o objeto atualizado
        except Exception as e:
            db.session.rollback()
            print(f"[API /api/trades PUT ERROR {trade_id}] Erro ao atualizar trade: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Erro interno ao atualizar trade: {str(e)}'}), 500

# ROTA Fechamento acionado por TP/SL (AJUSTADA para DB)
@app.route('/api/trades/<trade_id>/trigger_close', methods=['POST'])
@login_required
def handle_triggered_close(trade_id):
    print(f"[TRIGGER CLOSE DEBUG {trade_id}] Recebido POST.")
    data = request.json
    trigger_price_str = data.get('trigger_price')

    if trigger_price_str is None:
        return jsonify({'error': 'Preço de disparo (trigger_price) é obrigatório'}), 400

    try:
        trigger_price = float(trigger_price_str)
    except (ValueError, TypeError):
        return jsonify({'error': 'Preço de disparo inválido'}), 400

    trade = db.session.get(Trade, trade_id)
    if not trade:
        return jsonify({'error': 'Trade não encontrado'}), 404
    if trade.exit_price is not None:
        # Se já fechado, apenas retorna ok sem fazer nada.
        print(f"[TRIGGER CLOSE WARN {trade_id}] Trade já estava fechado.")
        return jsonify(trade.to_dict()), 200 # Retorna o estado atual

    try:
        # Define dados para fechamento
        trade.exit_price = trigger_price
        trade.closed_at_timestamp = datetime.utcnow()

        # Calcula PnL
        entry_price = trade.entry_price
        size = trade.size
        side = trade.side
        calculated_pnl = None # Default
        if entry_price is not None and size is not None and side is not None and trigger_price is not None:
            price_diff = trigger_price - entry_price
            raw_pnl = price_diff * size if side == 'long' else -price_diff * size
            # Arredonda PnL para um número razoável de casas decimais (ex: 4)
            calculated_pnl = round(raw_pnl, 4)
        trade.pnl = calculated_pnl
        print(f"[TRIGGER CLOSE DEBUG {trade_id}] PnL calculado: {trade.pnl}")

        # Recalcula taxa FINAL (incluindo saída)
        trade_data_for_fee = trade.to_dict()
        trade.calculated_fee = calculate_trade_fee(trade_data_for_fee)
        print(f"[TRIGGER CLOSE DEBUG {trade_id}] Taxa final recalculada: {trade.calculated_fee}")

        # Remove TP/SL
        trade.take_profit = None
        trade.stop_loss = None

        db.session.commit()
        print(f"[TRIGGER CLOSE DEBUG {trade_id}] Trade atualizado e salvo com exit_price={trigger_price}")

        # Retorna o trade atualizado
        return jsonify(trade.to_dict()), 200

    except Exception as e:
        db.session.rollback()
        print(f"[TRIGGER CLOSE ERROR {trade_id}] Erro: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Erro interno ao fechar trade por gatilho: {str(e)}'}), 500


# Rota de Estatísticas (AJUSTADA para DB e Pandas)
@app.route('/api/statistics', methods=['GET'])
@login_required
def get_statistics_route():
    try:
        print("[STATS DEBUG DB] Iniciando get_statistics com DB...")
        # Busca todos os trades do banco de dados
        all_trades_db = Trade.query.all()

        default_stats = {
            'total_pnl': 0.0, 'best_trade': {'pnl': 0.0, 'symbol': '-'}, 'worst_trade': {'pnl': 0.0, 'symbol': '-'},
            'best_symbol_pnl': 0.0, 'worst_symbol_pnl': 0.0, 'best_symbol': '-', 'worst_symbol': '-',
            'total_trades': 0, 'symbol_pnl': {}, 'total_fees': 0.0,
            'winning_trades_count': 0, 'losing_trades_count': 0
        }

        if not all_trades_db:
            print("[STATS DEBUG DB] Nenhum trade no DB. Retornando default.")
            return jsonify(default_stats)

        # Converte para DataFrame do Pandas
        trades_list = [
            {
                'id': t.id, 'symbol': t.symbol or '-', 'pnl': t.pnl,
                'exit_price': t.exit_price, 'calculated_fee': t.calculated_fee
            } for t in all_trades_db
        ]
        df = pd.DataFrame(trades_list)
        print(f"[STATS DEBUG DB] DataFrame criado com shape: {df.shape}")

        # --- Validações e Conversões Essenciais no DataFrame ---
        df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce').fillna(0)
        df['calculated_fee'] = pd.to_numeric(df['calculated_fee'], errors='coerce').fillna(0)
        df['exit_price'] = pd.to_numeric(df['exit_price'], errors='coerce') # NaN se não for número
        # ---------------------------------------------------------

        # Calcula PnL Total
        total_pnl = df['pnl'].sum()
        print(f"[STATS DEBUG DB] total_pnl={total_pnl}")

        # Calcula Taxas Totais (SOMENTE de trades FECHADOS)
        # Usar pd.notna() é mais robusto que != None
        closed_trades_df = df[pd.notna(df['exit_price'])]
        total_fees = closed_trades_df['calculated_fee'].sum()
        print(f"[STATS DEBUG DB] Taxas Totais SOMADAS (trades fechados): {total_fees}")

        # Conta Trades Vencedores/Perdedores (baseado no PnL salvo)
        winning_trades_count = df[df['pnl'] > 0].shape[0]
        losing_trades_count = df[df['pnl'] < 0].shape[0]
        print(f"[STATS DEBUG DB] Vencedores: {winning_trades_count}, Perdedores: {losing_trades_count}")

        # Encontra melhor/pior trade (usando dados do DataFrame)
        # Trata caso de DataFrame vazio ou com apenas NaN em PnL
        idx_max = df['pnl'].idxmax() if not df['pnl'].isnull().all() else None
        idx_min = df['pnl'].idxmin() if not df['pnl'].isnull().all() else None
        best_trade_row = df.loc[idx_max] if idx_max is not None else pd.Series({'pnl': 0.0, 'symbol': '-'})
        worst_trade_row = df.loc[idx_min] if idx_min is not None else pd.Series({'pnl': 0.0, 'symbol': '-'})
        print(f"[STATS DEBUG DB] Best trade: Pnl={best_trade_row['pnl']}, Symbol={best_trade_row['symbol']}")
        print(f"[STATS DEBUG DB] Worst trade: Pnl={worst_trade_row['pnl']}, Symbol={worst_trade_row['symbol']}")

        # Calcula PnL por Símbolo
        symbol_pnl = df.groupby('symbol')['pnl'].sum()
        print(f"[STATS DEBUG DB] symbol_pnl calculado:\n{symbol_pnl.to_string()}")

        best_symbol_pnl_val = symbol_pnl.max() if not symbol_pnl.empty else 0.0
        worst_symbol_pnl_val = symbol_pnl.min() if not symbol_pnl.empty else 0.0
        # Usa .iloc[0] em idxmax/idxmin se o índice não for o símbolo diretamente (pandas >= 1.0)
        best_symbol = symbol_pnl.idxmax() if not symbol_pnl.empty and pd.notna(symbol_pnl.max()) and symbol_pnl.max() != 0 else '-'
        worst_symbol = symbol_pnl.idxmin() if not symbol_pnl.empty and pd.notna(symbol_pnl.min()) and symbol_pnl.min() != 0 else '-'

        stats_result = {
            'total_pnl': round(total_pnl, 2),
            'best_trade': {'pnl': round(best_trade_row['pnl'], 2), 'symbol': best_trade_row['symbol']},
            'worst_trade': {'pnl': round(worst_trade_row['pnl'], 2), 'symbol': worst_trade_row['symbol']},
            'best_symbol_pnl': round(best_symbol_pnl_val, 2),
            'worst_symbol_pnl': round(worst_symbol_pnl_val, 2),
            'best_symbol': best_symbol,
            'worst_symbol': worst_symbol,
            'total_trades': len(df),
            'symbol_pnl': symbol_pnl.round(2).to_dict(),
            'total_fees': round(total_fees, 2),
            'winning_trades_count': winning_trades_count,
            'losing_trades_count': losing_trades_count
        }
        print(f"[STATS DEBUG DB] Estatísticas Finais: {stats_result}")
        return jsonify(stats_result)

    except Exception as e:
        print(f"[API /api/statistics ERROR] Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        # Retorna default stats em caso de erro grave
        # Cria um default aqui para garantir que exista no escopo do except
        default_stats_fallback = {
            'total_pnl': 0.0, 'best_trade': {'pnl': 0.0, 'symbol': '-'}, 'worst_trade': {'pnl': 0.0, 'symbol': '-'},
            'best_symbol_pnl': 0.0, 'worst_symbol_pnl': 0.0, 'best_symbol': '-', 'worst_symbol': '-',
            'total_trades': 0, 'symbol_pnl': {}, 'total_fees': 0.0,
            'winning_trades_count': 0, 'losing_trades_count': 0
        }
        return jsonify(default_stats_fallback), 500


# --- ROTAS PARA BALANÇO SPOT (AJUSTADAS para DB) ---

@app.route('/api/balances', methods=['GET'])
@login_required
def get_balances():
    print("[API BALANCES DB] GET /api/balances solicitado.")
    try:
        balances_db = Balance.query.all()
        # Converte para formato {symbol: amount}
        balances_dict = {bal.symbol: bal.amount for bal in balances_db}
        print(f"[API BALANCES DB] Retornando balanços: {balances_dict}")
        return jsonify(balances_dict)
    except Exception as e:
        print(f"[API /api/balances GET ERROR] {e}")
        return jsonify({"error": "Erro ao buscar saldos"}), 500

@app.route('/api/balances/deposit', methods=['POST'])
@login_required
def handle_deposit():
    print("[API BALANCES DB] POST /api/balances/deposit solicitado.")
    data = request.json
    symbol = data.get('symbol')
    amount_str = data.get('amount')

    if not symbol or amount_str is None:
        return jsonify({'error': 'Símbolo e quantidade são obrigatórios'}), 400

    try:
        amount = float(amount_str)
        if amount <= 0: raise ValueError("Quantidade deve ser positiva")
    except (ValueError, TypeError):
        return jsonify({'error': 'Quantidade inválida'}), 400

    try:
        # Busca ou cria o registro de balanço
        # Usar .with_for_update() se alta concorrência for esperada (mais complexo)
        balance = Balance.query.filter_by(symbol=symbol).first()
        if balance:
            balance.amount += amount
            print(f"[API BALANCES DB] Depositando {amount} para {symbol}. Novo saldo: {balance.amount}")
        else:
            balance = Balance(symbol=symbol, amount=amount)
            db.session.add(balance)
            print(f"[API BALANCES DB] Criando balanço e depositando {amount} para {symbol}.")

        db.session.commit()
        # Retorna TODOS os balanços atualizados
        balances_db = Balance.query.all()
        balances_dict = {bal.symbol: bal.amount for bal in balances_db}
        return jsonify({'message': 'Depósito realizado com sucesso', 'balances': balances_dict}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[API /api/balances/deposit POST ERROR] {e}")
        return jsonify({'error': f'Erro interno ao processar depósito: {str(e)}'}), 500

@app.route('/api/balances/withdraw', methods=['POST'])
@login_required
def handle_withdraw():
    print("[API BALANCES DB] POST /api/balances/withdraw solicitado.")
    data = request.json
    symbol = data.get('symbol')
    amount_str = data.get('amount')

    if not symbol or amount_str is None:
        return jsonify({'error': 'Símbolo e quantidade são obrigatórios'}), 400

    try:
        amount = float(amount_str)
        if amount <= 0: raise ValueError("Quantidade deve ser positiva")
    except (ValueError, TypeError):
        return jsonify({'error': 'Quantidade inválida'}), 400

    try:
        # Usar .with_for_update() se alta concorrência for esperada
        balance = Balance.query.filter_by(symbol=symbol).first()

        if not balance or balance.amount < amount:
             current_amount = balance.amount if balance else 0.0
             print(f"[API BALANCES DB] Erro saque: Saldo insuficiente {symbol}. Saldo: {current_amount}, Tentativa: {amount}")
             return jsonify({'error': 'Saldo insuficiente'}), 400

        balance.amount -= amount
        print(f"[API BALANCES DB] Sacando {amount} de {symbol}. Novo saldo: {balance.amount}")
        db.session.commit()

        # Retorna TODOS os balanços atualizados
        balances_db = Balance.query.all()
        balances_dict = {bal.symbol: bal.amount for bal in balances_db}
        return jsonify({'message': 'Saque realizado com sucesso', 'balances': balances_dict}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[API /api/balances/withdraw POST ERROR] {e}")
        return jsonify({'error': f'Erro interno ao processar saque: {str(e)}'}), 500

# --------------------------------

# Rota PnL do Dia (AJUSTADA para DB, usando closed_at_timestamp)
@app.route('/api/daily_pnl')
@login_required
def get_daily_pnl():
    """Calcula e retorna o PnL total dos trades fechados hoje."""
    try:
        # Define o início e fim do dia de HOJE em UTC
        # Isso é importante para consistência, assumindo que os timestamps são UTC
        today_start_utc = datetime.combine(date.today(), datetime.min.time())
        today_end_utc = datetime.combine(date.today(), datetime.max.time())

        print(f"[Daily PnL DB] Calculando PnL para {date.today()} (UTC range: {today_start_utc} a {today_end_utc})")

        # Soma o PnL de trades onde closed_at_timestamp está no dia de HOJE
        daily_pnl_sum = db.session.query(func.sum(Trade.pnl)).filter(
            Trade.closed_at_timestamp >= today_start_utc,
            Trade.closed_at_timestamp <= today_end_utc,
            Trade.pnl.isnot(None) # Garante que PnL não seja nulo
        ).scalar() or 0.0 # Retorna 0.0 se a soma for None (nenhum trade)

        print(f"[Daily PnL DB] Soma PnL calculada para hoje: {daily_pnl_sum}")
        return jsonify({'daily_pnl': round(daily_pnl_sum, 2)}) # Arredonda

    except Exception as e:
        print(f"[API /api/daily_pnl ERROR] Erro GERAL: {e}")
        return jsonify({'daily_pnl': 0.0}), 500


# Rota Taxas do Dia (AJUSTADA para DB, usando closed_at_timestamp)
@app.route('/api/daily_fees')
@login_required
def get_daily_fees():
    """Calcula e retorna a soma das taxas dos trades fechados hoje."""
    try:
        today_start_utc = datetime.combine(date.today(), datetime.min.time())
        today_end_utc = datetime.combine(date.today(), datetime.max.time())

        print(f"[Daily Fees DB] Calculando Taxas para {date.today()} (UTC range: {today_start_utc} a {today_end_utc})")

        # Soma calculated_fee de trades onde closed_at_timestamp está no dia de HOJE
        daily_fees_sum = db.session.query(func.sum(Trade.calculated_fee)).filter(
            Trade.closed_at_timestamp >= today_start_utc,
            Trade.closed_at_timestamp <= today_end_utc,
            Trade.calculated_fee.isnot(None) # Garante que taxa não seja nula
        ).scalar() or 0.0 # Retorna 0.0 se a soma for None

        print(f"[Daily Fees DB] Soma Taxas calculada para hoje: {daily_fees_sum}")
        return jsonify({'daily_fees': round(daily_fees_sum, 2)}) # Arredonda

    except Exception as e:
        print(f"[API /api/daily_fees ERROR] Erro GERAL: {e}")
        return jsonify({'daily_fees': 0.0}), 500

# ROTA DE DEBUG: Contar trades criados hoje (AJUSTADA para DB)
@app.route('/api/debug/trades_today_count')
@login_required
def count_trades_created_today():
    try:
        today_start_utc = datetime.combine(date.today(), datetime.min.time())
        today_end_utc = datetime.combine(date.today(), datetime.max.time())

        # Conta trades onde o timestamp ORIGINAL (criação) está no dia de HOJE
        count = Trade.query.filter(
            Trade.timestamp >= today_start_utc,
            Trade.timestamp <= today_end_utc
        ).count()

        print(f"[DEBUG COUNT DB] Número de trades criados hoje: {count}")
        return jsonify({'trades_created_today': count})
    except Exception as e:
        print(f"[DEBUG COUNT DB] Erro ao contar trades: {e}")
        return jsonify({'error': str(e)}), 500

# Helper Function: is_today (AJUSTADO para datetime objects)
# (Definida mais acima agora)

# Rota Histórico de PNL Líquido Diário (AJUSTADA para DB)
@app.route('/api/daily_pnl_history')
@login_required
def get_daily_pnl_history():
    try:
        # Agrupa por data de fechamento e soma PnL e Taxas
        # ATENÇÃO: Funções de data podem variar entre bancos de dados (DATE() funciona bem em SQLite e PostgreSQL)
        # Usar CAST para Date pode ser mais portável se DATE() não for universal
        # Exemplo com CAST: func.cast(Trade.closed_at_timestamp, db.Date)
        daily_summary = db.session.query(
            func.date(Trade.closed_at_timestamp).label('closure_date'),
            func.sum(Trade.pnl).label('pnl_sum'),
            func.sum(Trade.calculated_fee).label('fee_sum')
        ).filter(
            Trade.closed_at_timestamp.isnot(None),
            Trade.pnl.isnot(None),
            Trade.calculated_fee.isnot(None)
        ).group_by(
            func.date(Trade.closed_at_timestamp) # Agrupa pela data
        ).order_by(
            func.date(Trade.closed_at_timestamp).desc() # Ordena pela data desc
        ).all()

        history = []
        for result in daily_summary:
            # result.closure_date pode ser string ou date object dependendo do DB/driver
            closure_date_str = None
            if isinstance(result.closure_date, date):
                closure_date_str = result.closure_date.isoformat()
            elif isinstance(result.closure_date, str):
                 # Tenta parsear a string para validar e padronizar
                 try:
                      parsed_date = date.fromisoformat(result.closure_date)
                      closure_date_str = parsed_date.isoformat()
                 except ValueError:
                     print(f"[PNL History WARN] Formato de data inválido retornado do DB: {result.closure_date}")
                     continue # Pula esta entrada
            else:
                 print(f"[PNL History WARN] Tipo inesperado para closure_date: {type(result.closure_date)}")
                 continue # Pula esta entrada

            net_pnl = round((result.pnl_sum or 0.0) - (result.fee_sum or 0.0), 2)
            history.append({
                'date': closure_date_str,
                'net_pnl': net_pnl
            })

        print(f"[PNL History DB] Histórico calculado: {len(history)} dias.")
        # A ordenação já foi feita no banco de dados
        return jsonify(history)
    except Exception as e:
         print(f"[API /api/daily_pnl_history ERROR] {e}")
         import traceback
         traceback.print_exc()
         return jsonify({"error": "Erro ao buscar histórico de PNL diário"}), 500

# Rota Buscar Dados de Mercado (CoinGecko - Mantida como estava)
@app.route('/api/market_data')
@login_required
def get_market_data():
    # ... (código original mantido) ...
    # Pega os IDs da query string (ex: /api/market_data?ids=bitcoin,solana)
    ids_param = request.args.get('ids')
    if not ids_param:
        return jsonify({"error": "Parâmetro 'ids' é obrigatório"}), 400

    print(f"[Market Data API] Recebido pedido para IDs: {ids_param}")
    # Usar a API de mercados para obter preço e imagem
    market_url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids_param}&order=market_cap_desc&page=1&sparkline=false"
    
    market_data_response = {}
    try:
        response = requests.get(market_url, timeout=10) # Timeout de 10 segundos
        response.raise_for_status() # Lança erro para 4xx/5xx
        coins_data = response.json()
        
        # Formata a resposta para { id: { usd: price, image: url } }
        for coin in coins_data:
            market_data_response[coin['id']] = {
                'usd': coin.get('current_price'),
                'image': coin.get('image')
            }
        print(f"[Market Data API] Dados retornados da CoinGecko para {len(coins_data)} moedas.")

    except requests.exceptions.Timeout:
        print("[Market Data API] Erro: Timeout ao conectar com CoinGecko API.")
        return jsonify({"error": "Timeout ao buscar dados de mercado externos"}), 504 
    except requests.exceptions.RequestException as e:
        print(f"[Market Data API] Erro ao buscar dados da CoinGecko API: {e}")
        return jsonify({"error": "Erro ao buscar dados de mercado externos"}), 502 # Bad Gateway
    except Exception as e:
        print(f"[Market Data API] Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Erro interno do servidor ao processar dados de mercado"}), 500

    return jsonify(market_data_response)
# ------------------------------------------------------------


# --- COMENTADO: Funções de Migração e Inicialização Antigas ---
# def recalculate_initial_volume_and_contributions(tracker_instance): ...
# def clean_nan_in_trades(file_path): ...
# def migrate_historical_fees(): ...
# def migrate_closed_at_timestamps(): ...
# def migrate_historical_volume(): ...
# tracker = BackpackTracker() # Instanciação antiga
# clean_nan_in_trades(TRADES_FILE) # Limpeza antiga
# tracker.trades = load_trades() # Recarga antiga
# COMENTADO: recalculate_initial_volume_and_contributions(tracker) # Recálculo antigo
# migrate_closed_at_timestamps() # Migração antiga
# migrate_historical_volume()    # Migração antiga
# -----------------------------------------------------------


# --- CLI Commands ---

@app.cli.command("create-user")
@click.argument("email")
@click.password_option()
def create_user(email, password):
    """Creates a new user with the given email and password."""
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        print(f"Error: User with email {email} already exists.")
        return

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    # Use um ID simples ou gere um UUID se preferir
    # Para simplificar, vamos usar o email como parte do ID ou um contador simples
    # Contando usuários existentes para gerar um ID simples (não ideal para alta concorrência)
    user_count = User.query.count()
    new_user_id = str(user_count + 1)

    new_user = User(id=new_user_id, email=email, password_hash=hashed_password)
    db.session.add(new_user)
    try:
        db.session.commit()
        print(f"User {email} created successfully with ID {new_user_id}.")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating user: {e}")


# --- Inicialização Principal (Apenas para Desenvolvimento Local) ---
if __name__ == '__main__':
    # Garante que a pasta 'instance' exista para o SQLite
    try:
        if not os.path.exists(app.instance_path):
             os.makedirs(app.instance_path)
             print(f"Pasta 'instance' criada em: {app.instance_path}")
    except OSError as e:
         print(f"Erro ao criar pasta 'instance': {e}")

    # Cria as tabelas do banco de dados se não existirem
    # Em um fluxo com Flask-Migrate, 'flask db upgrade' cuidaria disso.
    # Mas para a primeira execução local, isso é útil.
    with app.app_context():
        print("Verificando/Criando tabelas do banco de dados...")
        # Garante que as tabelas sejam criadas no contexto da aplicação
        try:
            db.create_all()
            print("Tabelas OK.")
        except Exception as e:
             print(f"Erro ao criar tabelas: {e}")
             # Considerar sair se as tabelas não puderem ser criadas

        # Adicionar usuário padrão se não existir (apenas para dev)
        try:
            if not User.query.filter_by(email='leonardo_guimaraes@hotmail.com').first():
                print("Criando usuário padrão...")
                hashed_password = generate_password_hash('62845_Madhouse', method='pbkdf2:sha256')
                default_user = User(id='1', email='leonardo_guimaraes@hotmail.com', password_hash=hashed_password)
                db.session.add(default_user)
                db.session.commit()
                print("Usuário padrão criado.")
        except Exception as e:
             print(f"Erro ao criar usuário padrão: {e}")
             db.session.rollback()

        # Inicializa o valor de total_volume se não existir
        try:
             get_total_volume_from_db() # Chama para inicializar se necessário
        except Exception as e:
            print(f"Erro ao inicializar total_volume: {e}")

    print("Iniciando servidor Flask em modo DEBUG (APENAS DESENVOLVIMENTO)...")
    print(f"Acessível em: http://127.0.0.1:5000")
    print("AVISO: NÃO use este servidor em produção!")
    # ATENÇÃO: debug=True NUNCA deve ser usado em produção!
    app.run(debug=True, port=5000)
# -----------------------------------------------------------------------

