"""
Ferramenta de pesquisa web via DuckDuckGo.
"""

from duckduckgo_search import DDGS


def pesquisar_web(query: str, max_resultados: int = 5) -> str:
    """Pesquisa na web usando DuckDuckGo."""
    try:
        with DDGS() as ddgs:
            resultados = list(ddgs.text(query, max_results=max_resultados))

        if not resultados:
            return "Nenhum resultado encontrado."

        texto = f"Resultados para: '{query}'\n\n"
        for i, r in enumerate(resultados, 1):
            texto += f"{i}. {r['title']}\n"
            texto += f"   {r['body']}\n"
            texto += f"   Fonte: {r['href']}\n\n"

        return texto

    except Exception as e:
        return f"Erro na pesquisa: {str(e)}"
