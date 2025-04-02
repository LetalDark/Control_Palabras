import os
import sys
import unidecode
import sqlite3
import discord


from discord.ext import commands
from fuzzywuzzy import fuzz
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ROLE_ID = int(os.getenv("ROLE_ID"))
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID"))

# Ajusta el umbral de coincidencia (un valor entre 0 y 100, siendo 100 una coincidencia exacta)
UMBRAL_SIMILITUD = 80
# Obtener la lista de canales a revisar desde el .env
WATCH_CHANNELS = os.getenv("WATCH_CHANNELS")
WATCH_CHANNELS = [int(ch) for ch in WATCH_CHANNELS.split(",")] if WATCH_CHANNELS else []

# Configuración del bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Nombre correcto de la base de datos
DB_NAME = "Palabras.db"  # Asegúrate de que este es el nombre correcto

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

# Verificar si la base de datos existe
if not os.path.exists(DB_PATH):
    print(f"❌ ERROR: No se encontró la base de datos '{DB_NAME}'. Verifica el nombre y ubicación.")
    sys.exit(1)  # Sale del programa con código de error 1

print(f"✅ Base de datos encontrada: {DB_PATH}")

def obtener_palabras():
    """Obtiene las palabras almacenadas en la base de datos SQLite3."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT Palabra FROM Palabras")
    palabras = {row[0].lower() for row in cursor.fetchall()}
    conn.close()
    return palabras

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
async def on_message(message):
    if message.author == bot.user:
        return  # Ignorar mensajes del propio bot

    if message.content.startswith('!addword'):
        await bot.process_commands(message)

    if message.content.startswith('!delword'):
        await bot.process_commands(message)

    # Filtrar mensajes solo en los canales permitidos
    if message.channel.id not in WATCH_CHANNELS:
        return

    palabras_clave = obtener_palabras()

    # Función para tratar cada palabra
    def tratar_palabra(palabra):
        palabra = palabra.lower()  # 1.1.1 - Convertir a minúsculas
        palabra = unidecode.unidecode(palabra)  # 1.1.2 - Eliminar acentos
        palabra = convertir_vocales(palabra)  # 1.1.3 - Convertir números a vocales

        # 1.1.4 - Verificar similitud con fuzzywuzzy
        for palabra_clave in palabras_clave:
            palabra_clave_tratada = convertir_vocales(unidecode.unidecode(palabra_clave.lower()))
            if fuzz.ratio(palabra, palabra_clave_tratada) > UMBRAL_SIMILITUD:
                return palabra_clave_tratada  # Devuelve la palabra clave si hay coincidencia
        
        return None  # No hubo coincidencia

    # Dentro de on_message, donde envías "Detectado"
    
    embed = None
    # Procesar mensajes de texto normales
    palabras_mensaje = message.content.split()
    for palabra in palabras_mensaje:
        palabra_tratada = tratar_palabra(palabra)
        if palabra_tratada and palabra_tratada in palabras_clave:
            await enviar_mensaje(message,embed)
            return  # Rompe el bucle si detecta una palabra

    # Procesar mensajes dentro de embeds
    if message.embeds:
        for embed in message.embeds:
            if embed.description:
                palabras_embed = embed.description.split()
                for palabra in palabras_embed:
                    palabra_tratada = tratar_palabra(palabra)
                    if palabra_tratada and palabra_tratada in palabras_clave:
                        await enviar_mensaje(message,embed)
                        return  # Rompe el bucle si detecta una palabra

    await bot.process_commands(message)

async def enviar_mensaje(message,embed):
    
    channel_alert = bot.get_channel(ALERT_CHANNEL_ID)
    # Link mensaje
    message_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"

    # Pasamos embed o mensaje
    if embed and embed.description:
        mensaje_embed=embed.description
    else:
        mensaje_embed=message.content

    # Crear embed con el mensaje detectado
    embed = discord.Embed(
        description=mensaje_embed,
        color=discord.Color.red()
    )
    embed.set_author(name=message.author.display_name, icon_url=message.author.avatar.url if message.author.avatar else None)
    embed.set_footer(text=f"Canal: #{message.channel.name}")

    # Enviar el mensaje con mención y el embed
    await channel_alert.send(f"<@&{ROLE_ID}>\n🚨 *Palabra Detectada* 🚨\n➡️ [Ver mensaje]({message_link})\n", embed=embed)

@bot.command()
async def addword(ctx, *, palabra):

    # Verificar si el comando fue ejecutado en canal de ALERT_CHANNEL_ID
    if ctx.channel.id != ALERT_CHANNEL_ID:
        return

    """Añadir una palabra a la base de datos"""
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
    await ctx.send(f"✅ La palabra '{palabra_normalizada}' ha sido añadida correctamente.")
    conn.close()

@bot.command()
async def delword(ctx, *, palabra):

    # Verificar si el comando fue ejecutado en canal de ALERT_CHANNEL_ID
    if ctx.channel.id != ALERT_CHANNEL_ID:
        return

    """Quitar una palabra de la base de datos"""
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

# Iniciar el bot con tu token
bot.run(TOKEN)