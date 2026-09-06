"""Read-only eligibility guide. No age submission, account creation or storage."""
from pathlib import Path
from fastapi.responses import FileResponse, JSONResponse
from .connector_eligibility import catalog_snapshot


def install_routes(app):
    static = Path(__file__).parent / 'static'

    @app.get('/access-guide', include_in_schema=False)
    async def access_guide():
        return FileResponse(static / 'access-guide.html', headers={'Cache-Control': 'no-store'})

    @app.get('/api/connector-eligibility')
    async def eligibility_catalog():
        try:
            return JSONResponse(catalog_snapshot(), headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse({'error': 'eligibility_unavailable'}, status_code=503,
                                headers={'Cache-Control': 'no-store'})
