#!/usr/bin/env python3
"""
Generador de Reportes de Migración z/OS a GitHub
Analiza logs de Jenkins y genera un informe en formato Markdown
"""

import re
from pathlib import Path
from typing import Dict, List, Optional


class MigrationLogParser:
    """Parser para logs de migración z/OS"""
    
    def __init__(self, log_path: str):
        self.log_path = Path(log_path)
        self.log_content = self._read_log()
        
    def _read_log(self) -> str:
        """Lee el contenido del archivo de log"""
        with open(self.log_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def extract_general_info(self) -> Dict[str, str]:
        """Extrae información general del log"""
        info = {}
        
        # Usuario
        user_match = re.search(r'Started by user (.+)', self.log_content)
        info['user'] = user_match.group(1) if user_match else 'N/A'
        
        # Repositorio
        repo_match = re.search(r'git clone https://github\.com/[^/]+/([^\s]+)\.git', self.log_content)
        info['repository'] = repo_match.group(1) if repo_match else 'N/A'
        
        # Rama principal
        branch_match = re.search(r'Already on \'([^\']+)\'', self.log_content)
        info['main_branch'] = branch_match.group(1) if branch_match else 'main'
        
        # Commit principal (primer commit de la migración)
        commit_match = re.search(r'\[main ([a-f0-9]{7})\]', self.log_content)
        info['main_commit'] = commit_match.group(1) if commit_match else 'N/A'
        
        # Workspace
        workspace_match = re.search(r'Running on \w+ in ([^\s]+)', self.log_content)
        info['workspace'] = workspace_match.group(1) if workspace_match else 'N/A'
        
        # Estado final
        status_match = re.search(r'Finished: (\w+)', self.log_content)
        info['status'] = status_match.group(1) if status_match else 'UNKNOWN'
        
        return info
    
    def extract_environment_data(self, env_name: str) -> Dict:
        """Extrae datos de un entorno específico (EXPLO, PREP, INTE)"""
        env_data = {
            'name': env_name,
            'programs': 0,
            'copybooks': 0,
            'dclgens': 0,
            'jcls': 0,
            'total': 0,
            'errors': 0,
            'branch': 'main' if env_name == 'EXPLO' else f'feature/migrate-{env_name.lower()}',
            'commit': None,
            'datasets': [],
            'error_details': []
        }
        
        # Buscar sección del entorno
        pattern = rf'Migración {env_name}.*?(?=Migración \w+|stage.*?Declarative: Post Actions|$)'
        env_section = re.search(pattern, self.log_content, re.DOTALL | re.IGNORECASE)
        
        if not env_section:
            return env_data
        
        section_text = env_section.group(0)
        
        # Extraer datasets y contar archivos
        dataset_patterns = {
            'programs': (r'({}\.\w+\.FUENTES)'.format(env_name), r'Copying {}\.\w+\.FUENTES'.format(env_name)),
            'copybooks': (r'({}\.\w+\.COBOL)'.format(env_name), r'Copying {}\.\w+\.COBOL'.format(env_name)),
            'dclgens': (r'({}\.\w+\.DCLGEN)'.format(env_name), r'Copying {}\.\w+\.DCLGEN'.format(env_name)),
            'jcls': (r'({}\.\w+\.CNTL)'.format(env_name), r'Copying {}\.\w+\.CNTL'.format(env_name))
        }
        
        for key, (dataset_pattern, copy_pattern) in dataset_patterns.items():
            # Encontrar nombre del dataset
            dataset_match = re.search(dataset_pattern, section_text)
            if dataset_match:
                env_data['datasets'].append(dataset_match.group(1))
            
            # Contar archivos copiados
            count = len(re.findall(copy_pattern, section_text))
            env_data[key] = count
        
        env_data['total'] = sum([env_data['programs'], env_data['copybooks'], 
                                  env_data['dclgens'], env_data['jcls']])
        
        # Buscar errores
        error_matches = re.findall(r'\[ERROR\].*?([A-Z0-9]+).*?(?:errno=(\d+)|ABEND)', section_text)
        env_data['errors'] = len(error_matches)
        if error_matches:
            for match in error_matches:
                env_data['error_details'].append({
                    'file': match[0],
                    'errno': match[1] if len(match) > 1 else 'N/A'
                })
        
        # Extraer commit
        commit_match = re.search(r'\[(?:main|feature/migrate-\w+) ([a-f0-9]{7})\]', section_text)
        if commit_match:
            env_data['commit'] = commit_match.group(1)
        
        return env_data
    
    def parse(self) -> Dict:
        """Parsea todo el log y retorna la información estructurada"""
        data = {
            'general': self.extract_general_info(),
            'environments': []
        }
        
        # Detectar entornos migrados
        env_names = re.findall(r'Migración (\w+)', self.log_content)
        unique_envs = list(dict.fromkeys(env_names))  # Mantener orden y eliminar duplicados
        
        for env_name in unique_envs:
            env_data = self.extract_environment_data(env_name)
            data['environments'].append(env_data)
        
        return data


class MarkdownReportGenerator:
    """Generador de reportes en formato Markdown"""
    
    def __init__(self, data: Dict):
        self.data = data
        
    def generate_summary_table(self) -> str:
        """Genera la tabla de resumen ejecutivo"""
        general = self.data['general']
        env_count = len(self.data['environments'])
        env_names = ', '.join([env['name'] for env in self.data['environments']])
        
        return f"""## Resumen Ejecutivo

|  |  |
|---------|-------|
| **Estado de Ejecución** | {general['status']} |
| **Usuario** | {general['user']} |
| **Repositorio Destino** | {general['repository']} |
| **Rama Principal** | {general['main_branch']} |
| **Entornos Migrados** | {env_count} ({env_names}) |
| **Commit Principal** | {general['main_commit']} |
| **Workspace** | {general['workspace']} |
"""
    
    def generate_volumetry_table(self) -> str:
        """Genera la tabla de volumetría general"""
        envs = self.data['environments']
        
        # Cabecera
        headers = ['| Concepto |'] + [f' {env["name"]} |' for env in envs]
        separator = ['|----------|'] + ['------|' for _ in envs]
        
        # Filas
        rows = []
        rows.append(['| **Rama Destino** |'] + [f' {env["branch"]} |' for env in envs])
        rows.append(['| **Programas COBOL** |'] + [f' {env["programs"]} |' for env in envs])
        rows.append(['| **Copybooks** |'] + [f' {env["copybooks"]} |' for env in envs])
        rows.append(['| **DCLGENs** |'] + [f' {env["dclgens"]} |' for env in envs])
        rows.append(['| **JCLs** |'] + [f' {env["jcls"]} |' for env in envs])
        rows.append(['| **Total Archivos** |'] + [f' {env["total"]} |' for env in envs])
        rows.append(['| **Errores** |'] + [f' {env["errors"]}{"*" if env["errors"] > 0 else ""} |' for env in envs])
        
        table = ''.join(headers) + '\n' + ''.join(separator) + '\n'
        for row in rows:
            table += ''.join(row) + '\n'
        
        # Añadir nota de errores si hay alguno
        error_notes = []
        for env in envs:
            if env['errors'] > 0 and env['error_details']:
                for error in env['error_details']:
                    error_notes.append(f"Error en miembro {error['file']}: BSAM OPEN failed")
        
        if error_notes:
            table += '\n_*' + '; '.join(error_notes) + '_\n'
        
        return f"""## Volumetría General

{table}"""
    
    def generate_environment_section(self, env: Dict, index: int) -> str:
        """Genera la sección de un entorno específico"""
        env_descriptions = {
            'EXPLO': 'Migrar el entorno de explotación desde datasets z/OS a estructura Git.',
            'PREP': 'Migrar el entorno de preproducción a rama feature.',
            'INTE': 'Migrar el entorno de integración a rama feature.'
        }
        
        description = env_descriptions.get(env['name'], f'Migrar el entorno {env["name"]}.')
        
        # Datasets origen
        datasets_text = ''
        if env['programs'] > 0:
            datasets_text += f"- `{env['datasets'][0] if env['datasets'] else env['name'] + '.VPROG.FUENTES'}` → {env['programs']} programas COBOL\n"
        if env['copybooks'] > 0:
            datasets_text += f"- `{env['name']}.VCOPYS.COBOL` → {env['copybooks']} copybooks\n"
        if env['dclgens'] > 0:
            datasets_text += f"- `{env['name']}.VCOPYS.DCLGEN` → {env['dclgens']} DCLGENs\n"
        if env['jcls'] > 0:
            datasets_text += f"- `{env['name']}.JCL.CNTL` → {env['jcls']} JCLs\n"
        
        # Resultado
        result_text = f"- ✅ {env['total']} archivos migrados"
        if env['errors'] > 0:
            result_text += f"\n- ❌ {env['errors']} error"
            if env['error_details']:
                error_info = env['error_details'][0]
                result_text += f": `{error_info['file']}` (BSAM OPEN failed, errno={error_info['errno']})"
        else:
            result_text += " exitosamente"
        
        if env['commit']:
            result_text += f"\n- Commit: `{env['commit']}` - \"migracion {env['name']}\""
        
        result_text += f"\n- {'Push exitoso' if env['name'] == 'EXPLO' else 'Branch creado y pushed'} a rama `{env['branch']}`"
        
        if env['name'] != 'EXPLO':
            result_text += f"\n- PR disponible en: `/pull/new/{env['branch']}`"
        
        return f"""### {index}. Migración {env['name']} ({'Explotación' if env['name'] == 'EXPLO' else 'Preproducción' if env['name'] == 'PREP' else 'Integración'})

{description}

**Datasets Origen:**
{datasets_text}
**Proceso:**
- Rama {'destino' if env['name'] == 'EXPLO' else 'creada'}: `{env['branch']}`
- {'Limpieza previa de directorios' if env['name'] != 'EXPLO' else 'Directorio destino: `/usr/lpp/IDZ/jenkins/workspace/.../esp-dvi-app-mainframe`'}
- Codificación: IBM-1145

**Resultado:**
{result_text}
"""
    
    def generate_technical_observations(self) -> str:
        """Genera la sección de observaciones técnicas"""
        # Recopilar incidencias
        incidents_text = ''
        incident_num = 1
        
        for env in self.data['environments']:
            if env['errors'] > 0 and env['error_details']:
                for error in env['error_details']:
                    incidents_text += f"{incident_num}. **Error BSAM** en archivo `{error['file']}` durante migración {env['name']}\n"
                    incidents_text += f"   - Error code: `0x130018`\n"
                    incidents_text += f"   - Tipo: BSAM OPEN failed\n"
                    incidents_text += f"   - Impacto: 1 archivo no migrado de {env['total']} totales\n\n"
                    incident_num += 1
        
        if not incidents_text:
            incidents_text = 'No se registraron incidencias durante el proceso de migración.\n'
        
        return f"""## Observaciones Técnicas

### Patrones de Nomenclatura
- Programas COBOL: `B471J*.cbl`, `VB4700*.cbl`, `VI471001.cbl`
- Copybooks: `R470JBE*.cpy`, `X*.cpy`
- DCLGENs: `T47*.cpy`
- JCLs: `X03247*.jcl`

### Incidencias
{incidents_text}"""
    
    def generate_conclusions(self) -> str:
        """Genera las conclusiones del reporte"""
        total_files = sum(env['total'] for env in self.data['environments'])
        total_errors = sum(env['errors'] for env in self.data['environments'])
        success_rate = ((total_files - total_errors) / total_files * 100) if total_files > 0 else 100
        
        env_count = len(self.data['environments'])
        feature_branches = [env['name'] for env in self.data['environments'] if env['name'] != 'EXPLO']
        
        conclusions = f"✅ Migración completada exitosamente con tasa de éxito del **{success_rate:.1f}%**  \n"
        conclusions += f"✅ {env_count} entornos migrados con estructura consistente  \n"
        
        if feature_branches:
            branches_str = ' y '.join(feature_branches)
            conclusions += f"✅ Ramas feature creadas para {branches_str}  \n"
        
        conclusions += "✅ Sistema de trazabilidad mediante logs configurado  \n"
        
        if total_errors > 0:
            for env in self.data['environments']:
                if env['errors'] > 0 and env['error_details']:
                    for error in env['error_details']:
                        conclusions += f"⚠️ 1 archivo requiere revisión manual ({error['file']})\n"
        
        return f"""## Conclusiones

{conclusions}"""
    
    def generate(self) -> str:
        """Genera el reporte completo en Markdown"""
        report = "# Reporte de Migración z/OS a GitHub\n\n"
        report += self.generate_summary_table() + "\n"
        report += self.generate_volumetry_table() + "\n"
        report += "---\n\n## Desglose por Fase\n\n"
        
        for i, env in enumerate(self.data['environments'], 1):
            report += self.generate_environment_section(env, i)
            if i < len(self.data['environments']):
                report += "\n---\n\n"
        
        report += "\n---\n\n"
        report += self.generate_technical_observations() + "\n"
        report += "\n---\n\n"
        report += self.generate_conclusions()
        
        return report


def main():
    """Función principal"""
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python zos_migration_report_generator.py <archivo_log> [archivo_salida]")
        sys.exit(1)
    
    log_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "Reporte_Migracion_zOS_GitHub.md"
    
    try:
        # Parsear el log
        print(f"📖 Analizando log: {log_file}")
        parser = MigrationLogParser(log_file)
        data = parser.parse()
        
        print(f"✅ Log parseado correctamente")
        print(f"   - Entornos encontrados: {len(data['environments'])}")
        print(f"   - Usuario: {data['general']['user']}")
        print(f"   - Repositorio: {data['general']['repository']}")
        
        # Generar reporte
        print(f"\n📝 Generando reporte Markdown...")
        generator = MarkdownReportGenerator(data)
        report = generator.generate()
        
        # Guardar archivo
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"✅ Reporte generado exitosamente: {output_file}")
        
    except FileNotFoundError:
        print(f"❌ Error: No se encontró el archivo {log_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error inesperado: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()