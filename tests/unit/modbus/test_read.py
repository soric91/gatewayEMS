"""
Unit tests for src/Modbus/read.py

Tests para las funciones de lectura Modbus:
- read_slave_data(): Lectura de un esclavo individual
- read_registers(): Lectura de múltiples esclavos (orquestación)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.Modbus.read import read_slave_data, read_registers


class TestReadSlaveData:
    """Tests para read_slave_data() - Función de lectura individual"""
    
    @pytest.mark.asyncio
    async def test_read_slave_data_holding_registers_success(self):
        """✅ Lectura exitosa de holding registers (function code 3)"""
        # ARRANGE: Crear mock del cliente Modbus
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # Mock de la respuesta exitosa
        mock_response = MagicMock()
        mock_response.isError.return_value = False
        mock_response.registers = [100, 200, 300]
        
        mock_client.read_holding_registers.return_value = mock_response
        
        # ACT: Llamar a la función
        result = await read_slave_data(
            client=mock_client,
            slave=1,
            address=0,
            count=3,
            function_code=3
        )
        
        # ASSERT: Verificar resultado
        assert result == [100, 200, 300]
        mock_client.read_holding_registers.assert_called_once_with(
            address=0,
            count=3,
            device_id=1
        )
    
    @pytest.mark.asyncio
    async def test_read_slave_data_input_registers_success(self):
        """✅ Lectura exitosa de input registers (function code 4)"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        mock_response = MagicMock()
        mock_response.isError.return_value = False
        mock_response.registers = [50, 60, 70]
        
        mock_client.read_input_registers.return_value = mock_response
        
        # ACT
        result = await read_slave_data(
            client=mock_client,
            slave=2,
            address=10,
            count=3,
            function_code=4  # Input registers
        )
        
        # ASSERT
        assert result == [50, 60, 70]
        mock_client.read_input_registers.assert_called_once_with(
            address=10,
            count=3,
            device_id=2
        )
    
    @pytest.mark.asyncio
    async def test_read_slave_data_client_not_connected(self):
        """❌ Cliente no conectado debe retornar None"""
        mock_client = AsyncMock()
        mock_client.connected = False  # ❌ No conectado
        
        result = await read_slave_data(
            client=mock_client,
            slave=1,
            address=0,
            count=3
        )
        
        assert result is None
        # Verificar que no intentó leer
        mock_client.read_holding_registers.assert_not_called()
        mock_client.read_input_registers.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_read_slave_data_modbus_error_response(self):
        """❌ Error de Modbus debe retornar None"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        mock_response = MagicMock()
        mock_response.isError.return_value = True  # ❌ Error
        
        mock_client.read_holding_registers.return_value = mock_response
        
        result = await read_slave_data(
            client=mock_client,
            slave=1,
            address=0,
            count=3,
            function_code=3
        )
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_read_slave_data_invalid_function_code(self):
        """❌ Código de función inválido retorna None (excepción capturada)"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # El ValueError es capturado por el except Exception general
        result = await read_slave_data(
            client=mock_client,
            slave=1,
            address=0,
            count=3,
            function_code=99  # ❌ Inválido (solo 3 o 4 son válidos)
        )
        
        # Debe retornar None porque la excepción es capturada
        assert result is None
    
    @pytest.mark.asyncio
    async def test_read_slave_data_exception_handling(self):
        """❌ Excepción inesperada debe retornar None y loggear"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # Simular excepción durante la lectura
        mock_client.read_holding_registers.side_effect = Exception("Connection lost")
        
        result = await read_slave_data(
            client=mock_client,
            slave=1,
            address=0,
            count=3,
            function_code=3
        )
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_read_slave_data_different_addresses(self):
        """✅ Leer desde diferentes direcciones"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        mock_response = MagicMock()
        mock_response.isError.return_value = False
        mock_response.registers = [111, 222]
        
        mock_client.read_holding_registers.return_value = mock_response
        
        result = await read_slave_data(
            client=mock_client,
            slave=5,
            address=1000,  # Dirección alta
            count=2,
            function_code=3
        )
        
        assert result == [111, 222]
        mock_client.read_holding_registers.assert_called_once_with(
            address=1000,
            count=2,
            device_id=5
        )


class TestReadRegisters:
    """Tests para read_registers() - Orquestación de múltiples lecturas"""
    
    @pytest.mark.asyncio
    async def test_read_registers_single_slave_single_address(self):
        """✅ Lectura de un solo esclavo, una dirección"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # Mock read_slave_data
        with patch('src.Modbus.read.read_slave_data', new_callable=AsyncMock) as mock_read:
            mock_read.return_value = [100, 200, 300]
            
            result = await read_registers(
                client=mock_client,
                slave=1,
                address=0,
                count=3,
                function_code=3
            )
            
            # Verificar resultado
            assert result == {1: [100, 200, 300]}
            
            # Verificar que se llamó read_slave_data correctamente
            mock_read.assert_called_once_with(
                client=mock_client,
                slave=1,
                address=0,
                count=3,
                function_code=3
            )
    
    @pytest.mark.asyncio
    async def test_read_registers_multiple_slaves(self):
        """✅ Lectura de múltiples esclavos en paralelo"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # IMPORTANTE: Con slaves=[1,2,3] y address=0, se expande a address=[0,0,0]
        # Cada slave hace asyncio.gather sobre zip([0,0,0], [2,2,2])
        # Entonces cada slave lee 3 veces la misma dirección
        
        # Simular diferentes datos por esclavo
        async def mock_read_slave(client, slave, address, count, function_code):
            return [slave * 100, slave * 200]
        
        with patch('src.Modbus.read.read_slave_data', side_effect=mock_read_slave):
            result = await read_registers(
                client=mock_client,
                slave=[1, 2, 3],
                address=0,  # Se expande a [0, 0, 0] por los 3 slaves
                count=2,
                function_code=3
            )
            
            # Cada esclavo lee 3 veces (una por cada address en la lista expandida)
            # Los datos se consolidan: [100, 200, 100, 200, 100, 200]
            assert result == {
                1: [100, 200, 100, 200, 100, 200],  # 3 lecturas consolidadas
                2: [200, 400, 200, 400, 200, 400],
                3: [300, 600, 300, 600, 300, 600]
            }
    
    @pytest.mark.asyncio
    async def test_read_registers_multiple_addresses_per_slave(self):
        """✅ Lectura de múltiples direcciones por esclavo (consolidadas)"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # Simular datos diferentes por dirección
        call_count = [0]
        async def mock_read_slave(client, slave, address, count, function_code):
            call_count[0] += 1
            if call_count[0] == 1:  # Primera llamada (address=0)
                return [10, 20]
            else:  # Segunda llamada (address=100)
                return [30, 40]
        
        with patch('src.Modbus.read.read_slave_data', side_effect=mock_read_slave):
            result = await read_registers(
                client=mock_client,
                slave=1,
                address=[0, 100],  # 2 direcciones
                count=[2, 2],
                function_code=3
            )
            
            # Los datos deben estar consolidados
            assert result == {1: [10, 20, 30, 40]}
    
    @pytest.mark.asyncio
    async def test_read_registers_client_reconnects(self):
        """✅ Cliente desconectado intenta reconectar"""
        mock_client = AsyncMock()
        mock_client.connected = False  # Inicialmente desconectado
        
        # Simular reconexión exitosa
        async def connect_side_effect():
            mock_client.connected = True
        
        mock_client.connect = AsyncMock(side_effect=connect_side_effect)
        
        with patch('src.Modbus.read.read_slave_data', new_callable=AsyncMock) as mock_read:
            mock_read.return_value = [100]
            
            result = await read_registers(
                client=mock_client,
                slave=1,
                address=0,
                count=1
            )
            
            # Debe haber intentado conectar
            mock_client.connect.assert_called_once()
            
            # Y retornar datos
            assert result == {1: [100]}
    
    @pytest.mark.asyncio
    async def test_read_registers_connection_fails(self):
        """❌ Fallo en reconexión debe lanzar ConnectionError"""
        mock_client = AsyncMock()
        mock_client.connected = False
        
        # Conexión falla (sigue desconectado)
        async def connect_fails():
            mock_client.connected = False  # Sigue desconectado
        
        mock_client.connect = AsyncMock(side_effect=connect_fails)
        
        with pytest.raises(ConnectionError, match="Cliente Modbus no conectado"):
            await read_registers(
                client=mock_client,
                slave=1,
                address=0,
                count=1
            )
    
    @pytest.mark.asyncio
    async def test_read_registers_address_count_mismatch(self):
        """❌ address y count de diferente tamaño debe lanzar ValueError"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        with pytest.raises(ValueError, match="deben ser listas del mismo tamaño"):
            await read_registers(
                client=mock_client,
                slave=1,
                address=[0, 100, 200],  # 3 elementos
                count=[3, 3]             # 2 elementos ❌
            )
    
    @pytest.mark.asyncio
    async def test_read_registers_filters_none_responses(self):
        """✅ Filtrar respuestas None (errores de lectura)"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # Algunas lecturas fallan (retornan None)
        call_count = [0]
        async def mock_read_slave(client, slave, address, count, function_code):
            call_count[0] += 1
            if call_count[0] == 1:
                return [10, 20]  # ✅ Exitoso
            else:
                return None  # ❌ Fallo
        
        with patch('src.Modbus.read.read_slave_data', side_effect=mock_read_slave):
            result = await read_registers(
                client=mock_client,
                slave=1,
                address=[0, 100],
                count=[2, 2]
            )
            
            # Solo debe incluir datos exitosos
            assert result == {1: [10, 20]}  # Sin los None
    
    @pytest.mark.asyncio
    async def test_read_registers_handles_slave_exception(self):
        """❌ Excepción en un esclavo no debe detener otros"""
        mock_client = AsyncMock()
        mock_client.connected = True
        
        # Primer esclavo falla, segundo funciona
        # Con 2 slaves y address=0, se expande a [0, 0]
        # Cada slave lee 2 veces
        async def mock_read_slave(client, slave, address, count, function_code):
            if slave == 1:
                raise Exception("Slave 1 error")
            else:
                return [200, 300]
        
        with patch('src.Modbus.read.read_slave_data', side_effect=mock_read_slave):
            result = await read_registers(
                client=mock_client,
                slave=[1, 2],
                address=0,  # Se expande a [0, 0]
                count=2
            )
            
            # Esclavo 1 no debe estar en resultados (su excepción fue capturada)
            assert 1 not in result
            # Esclavo 2 lee 2 veces (consolidado)
            assert result[2] == [200, 300, 200, 300]
