import os
import sys
import logging
import unidecode
import sqlite3
import discord


from discord.ext import commands
from fuzzywuzzy import fuzz
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
load_dotenv()

# Lista de claves requeridas
required_keys = [
    "DISCORD_TOKEN", "ROLE_IDS", "ALERT_CHANNEL_ID", "WATCH_CHANNELS_ID"
]
# Verificar que todas las claves existen y tienen valor
missing_keys = [key for key in required_keys if not os.environ.get(key)]
if missing_keys:
    logging.error(f"Error: Faltan los siguientes parametros por configurar: {', '.join(missing_keys)}")
    sys.exit(1)  # Salir del script con error

# Cargar variables del archivo .env
TOKEN = os.getenv("DISCORD_TOKEN")
PERMISSION_ROLES = list(map(int, os.getenv("PERMISSION_ROLES").split(",")))
ROLE_IDS = os.getenv("ROLE_IDS")
# Coger roles - Convertir la cadena en una lista de IDs
ROLE_ID = ' '.join(f"<@&{role_id}>" for role_id in ROLE_IDS.split(','))
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID"))
# Obtener la lista de canales a revisar desde el .env
try:
    WATCH_CHANNELS_ID = list(map(int, os.getenv("WATCH_CHANNELS_ID", "").split(',')))
except ValueError:
    logging.error("WATCH_CHANNELS_ID contiene valores no numéricos.")
    sys.exit(1)
# Ajusta el umbral de coincidencia (un valor entre 0 y 100, siendo 100 una coincidencia exacta)
UMBRAL_SIMILITUD = 80

# Configuración del bot
intents = discord.Intents.default()
intents.members = True 
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Nombre correcto de la base de datos
DB_NAME = "Palabras.db"  # Asegúrate de que este es el nombre correcto

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

def obtener_palabras():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT Palabra FROM Palabras")
        palabras = {row[0].lower() for row in cursor.fetchall()}
        conn.close()
        return palabras
    except Exception as e:
        logging.error(f"Error obteniendo palabras: {e}")
        return set()

# Comprueba si tiene permiso
def tiene_roles_id(*ids_roles):
    async def predicate(ctx):
        return any(role.id in ids_roles for role in ctx.author.roles)
    return commands.check(predicate)

def obtener_excepciones():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT Palabra FROM Excepciones")
        excepciones = {row[0].lower() for row in cursor.fetchall()}
        conn.close()
        return excepciones
    except Exception as e:
        logging.error(f"Error obteniendo excepciones: {e}")
        return set()

# Función para convertir vocales en números
def convertir_vocales(texto):
    mapeo = str.maketrans({
        '4': 'a',
        '3': 'e',
        '1': 'i',
        '0': 'o',
        '7': 'u'
    })
    return texto.translate(mapeo)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("⛔ No tienes permisos para usar este comando.")
    else:
        logging.error(f"Error ejecutando comando: {error}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return  # Ignorar mensajes del propio bot

    if message.content.startswith('!'):
        await bot.process_commands(message)
        return

    # Filtrar mensajes solo en los canales permitidos
    if message.channel.id not in WATCH_CHANNELS_ID:
        return

    palabras_clave = obtener_palabras()
    palabras_excepciones = obtener_excepciones()


    # Función para tratar cada palabra
    def tratar_palabra(palabra):
        palabra = palabra.lower()  # 1.1.1 - Convertir a minúsculas
        palabra = unidecode.unidecode(palabra)  # 1.1.2 - Eliminar acentos
        palabra = convertir_vocales(palabra)  # 1.1.3 - Convertir números a vocales

        # Si la palabra esta en excepciones la descartamos
        if palabra in palabras_excepciones:
            return None

        # 1.1.4 - Verificar similitud con fuzzywuzzy
        for palabra_clave in palabras_clave:
            palabra_clave_tratada = convertir_vocales(unidecode.unidecode(palabra_clave.lower()))
                  
            if fuzz.ratio(palabra, palabra_clave_tratada) > UMBRAL_SIMILITUD:
                return palabra_clave_tratada  # Devuelve la palabra clave si hay coincidencia        
        return None  # No hubo coincidencia

    embed = None
    # Procesar mensajes de texto normales
    palabras_mensaje = message.content.split()
    for palabra in palabras_mensaje:
        palabra_tratada = tratar_palabra(palabra)
        if palabra_tratada in palabras_clave:
            await enviar_mensaje(message,embed,palabra_tratada)
            return  # Rompe el bucle si detecta una palabra

    # Procesar mensajes dentro de embeds
    if message.embeds:
        for embed in message.embeds:
            if embed.description:
                palabras_embed = embed.description.split()
                for palabra in palabras_embed:
                    palabra_tratada = tratar_palabra(palabra)
                    if palabra_tratada in palabras_clave:
                        await enviar_mensaje(message,embed,palabra_tratada)
                        return  # Rompe el bucle si detecta una palabra

    await bot.process_commands(message)

async def enviar_mensaje(message,embed,palabra_tratada):
    try:    
        channel_alert = bot.get_channel(ALERT_CHANNEL_ID)
        # Link mensaje
        message_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"

        # Pasamos embed o mensaje
        if embed and embed.description:
            mensaje_autor=embed.author.name
            mensaje_embed=embed.description
        else:
            mensaje_autor="Sin Autor"
            mensaje_embed=message.content

        # Crear embed con el mensaje detectado
        embed = discord.Embed(
            title=mensaje_autor,
            description=mensaje_embed,
            color=discord.Color.red()
        )
        embed.set_author(name=f'{message.author.display_name} - {mensaje_autor}', icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.set_footer(text=f"Canal: #{message.channel.name}")

        # Enviar el mensaje con las menciones y el embed
        await channel_alert.send(f"{ROLE_ID}\n🚨 Palabra Detectada: **{palabra_tratada}** 🚨\n➡️ [Ver mensaje]({message_link})\n", embed=embed)
    except Exception as e:
        logging.error(f"Error al enviar mensaje de alerta: {e}")

@bot.command()
@tiene_roles_id(*PERMISSION_ROLES)
async def addword(ctx, *, palabra):

    # Verificar si el comando fue ejecutado en canal de ALERT_CHANNEL_ID
    if ctx.channel.id != ALERT_CHANNEL_ID:
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Normalizar la palabra: quitar mayúsculas, quitar acentos y convertir a minúsculas
        palabra_normalizada = unidecode.unidecode(palabra.strip()).lower()
        
        # Verificar si la palabra ya existe en la base de datos
        cursor.execute("SELECT COUNT(*) FROM Palabras WHERE Palabra = ?", (palabra_normalizada,))
        if cursor.fetchone()[0] > 0:
            await ctx.send(f"⚠️ La palabra '{palabra_normalizada}' ya existe en la base de datos.")
            conn.close()
            return
        
        # Si no existe, insertamos la palabra
        cursor.execute("INSERT INTO Palabras (Palabra) VALUES (?)", (palabra_normalizada,))
        conn.commit()
        conn.close()
        await ctx.send(f"✅ La palabra '{palabra_normalizada}' ha sido añadida correctamente.")
    except Exception as e:
        logging.error(f"Error en 'addword': {e}")
        await ctx.send("Ocurrió un error al añadir la palabra.")

@bot.command()
@tiene_roles_id(*PERMISSION_ROLES)
async def delword(ctx, *, palabra):

    # Verificar si el comando fue ejecutado en canal de ALERT_CHANNEL_ID
    if ctx.channel.id != ALERT_CHANNEL_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Normalizar la palabra y convertirla a minúsculas
    palabra_normalizada = palabra.strip().lower()
    
    # Verificar si la palabra existe en la base de datos
    cursor.execute("SELECT COUNT(*) FROM Palabras WHERE Palabra = ?", (palabra_normalizada,))
    if cursor.fetchone()[0] == 0:
        await ctx.send(f"⚠️ La palabra '{palabra_normalizada}' no existe en la base de datos.")
        conn.close()
        return
    
    # Si la palabra existe, eliminarla
    cursor.execute("DELETE FROM Palabras WHERE Palabra = ?", (palabra_normalizada,))
    conn.commit()
    await ctx.send(f"✅ La palabra '{palabra_normalizada}' ha sido eliminada correctamente.")
    conn.close()
    
@bot.command()
@tiene_roles_id(*PERMISSION_ROLES)
async def showwords(ctx):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Palabras ORDER BY palabra ASC")
        palabras = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM Palabras")
        totales = cursor.fetchone()[0]
        
        if not palabras:
            await ctx.send("⚠️ No hay palabras en la base de datos.")
            return
        
        palabras_lista = [p[0] for p in palabras]
        chunk = f'Palabras totales: {totales} \n'
        
        for palabra in palabras_lista:
            if len(chunk) + len(palabra) + 2 > 2000:
                await ctx.send(chunk)
                chunk = palabra
            else:
                chunk += f", {palabra}" if chunk else palabra
        
        if chunk:
            await ctx.send(chunk)
    
    except Exception as e:
        logging.error(f"Error en 'showwords': {str(e)}")


@bot.command()
@tiene_roles_id(*PERMISSION_ROLES)
async def addexcepcion(ctx, *, palabra):
    # Verificar si el comando fue ejecutado en canal de ALERT_CHANNEL_ID
    if ctx.channel.id != ALERT_CHANNEL_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Normalizar la palabra: quitar mayúsculas, quitar acentos y convertir a minúsculas
    palabra_normalizada = unidecode.unidecode(palabra.strip()).lower()
    
    # Verificar si la palabra ya existe en la base de datos
    cursor.execute("SELECT COUNT(*) FROM Excepciones WHERE Palabra = ?", (palabra_normalizada,))
    if cursor.fetchone()[0] > 0:
        await ctx.send(f"⚠️ La palabra '{palabra_normalizada}' ya existe en la base de datos de excepciones.")
        conn.close()
        return
    
    # Si no existe, insertamos la palabra
    cursor.execute("INSERT INTO Excepciones (Palabra) VALUES (?)", (palabra_normalizada,))
    conn.commit()
    await ctx.send(f"✅ La palabra '{palabra_normalizada}' ha sido añadida correctamente en excepciones.")
    conn.close()

@bot.command()
@tiene_roles_id(*PERMISSION_ROLES)
async def delexcepcion(ctx, *, palabra):

    # Verificar si el comando fue ejecutado en canal de ALERT_CHANNEL_ID
    if ctx.channel.id != ALERT_CHANNEL_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Normalizar la palabra y convertirla a minúsculas
    palabra_normalizada = palabra.strip().lower()
    
    # Verificar si la palabra existe en la base de datos
    cursor.execute("SELECT COUNT(*) FROM Excepciones WHERE Palabra = ?", (palabra_normalizada,))
    if cursor.fetchone()[0] == 0:
        await ctx.send(f"⚠️ La palabra '{palabra_normalizada}' no existe en la base de datos de excepciones.")
        conn.close()
        return
    
    # Si la palabra existe, eliminarla
    cursor.execute("DELETE FROM Excepciones WHERE Palabra = ?", (palabra_normalizada,))
    conn.commit()
    await ctx.send(f"✅ La palabra '{palabra_normalizada}' ha sido eliminada correctamente de excepciones.")
    conn.close()
    
@bot.command()
@tiene_roles_id(*PERMISSION_ROLES)
async def showexcepciones(ctx):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
            
        cursor.execute("SELECT * FROM Excepciones ORDER BY palabra ASC")
        palabras = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM Excepciones")
        totales = cursor.fetchone()[0]
        
        conn.close()
        
        if not palabras:
            await ctx.send("⚠️ No hay palabras en la base de datos de excepciones.")
            return
        palabras_lista = [p[0] for p in palabras]
        
        chunk = f'Palabras totales: {totales} \n'
        for palabra in palabras_lista:
            if len(chunk) + len(palabra) + 2 > 2000:
                await ctx.send(chunk)
                chunk = palabra
            else:
                chunk += f", {palabra}" if chunk else palabra

        if chunk:
            await ctx.send(chunk)
    except Exception as e:
        logging.error(f"Error en 'showexcepciones': {str(e)}")

def verificar_o_crear_db():
    if not os.path.exists(DB_PATH):
        logging.error(f"ERROR: No se encontró la base de datos '{DB_NAME}'. Verifica el nombre y ubicación.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Palabras (
            Palabra TEXT NOT NULL UNIQUE,
            PRIMARY KEY (Palabra)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Excepciones (
            Palabra TEXT NOT NULL UNIQUE,
            PRIMARY KEY (Palabra)
        )
    """)

    conn.commit()
    conn.close()
    
verificar_o_crear_db()

# Iniciar el bot con tu token
bot.run(TOKEN)