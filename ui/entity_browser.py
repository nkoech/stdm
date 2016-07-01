"""
/***************************************************************************
Name                 : Entity Browser Dialog
Description          : Dialog for browsing entity data based on the specified
                       database model.
Date                 : 18/February/2014 
copyright            : (C) 2015 by UN-Habitat and implementing partners.
                       See the accompanying file CONTRIBUTORS.txt in the root
email                : stdm@unhabitat.org
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from datetime import date
from collections import OrderedDict

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from stdm.data.configuration import entity_model
from stdm.data.configuration.columns import (
    MultipleSelectColumn,
    VirtualColumn
)
from stdm.data.configuration.entity import Entity
from stdm.data.pg_utils import table_column_names
from stdm.data.qtmodels import (
    BaseSTDMTableModel,
    VerticalHeaderSortFilterProxyModel
)
from stdm.ui.forms.widgets import ColumnWidgetRegistry
from stdm.navigation import TableContentGroup
from stdm.ui.forms.editor_dialog import EntityEditorDialog
from .admin_unit_manager import VIEW,MANAGE,SELECT
from .ui_entity_browser import Ui_EntityBrowser
from .helpers import SupportsManageMixin
from .notification import NotificationBar

__all__ = ["EntityBrowser", "EntityBrowserWithEditor",
           "ContentGroupEntityBrowser"]

class EntityBrowser(QDialog,Ui_EntityBrowser,SupportsManageMixin):
    """
    Dialog for browsing entity records in a table view.
    """
    
    '''
    Custom signal that is raised when the dialog is in SELECT state. It contains
    the record id of the selected row.
    '''
    recordSelected = pyqtSignal(int)
    
    def __init__(self, entity, parent=None, state=MANAGE):
        QDialog.__init__(self,parent)
        self.setupUi(self)
        SupportsManageMixin.__init__(self, state)

        self._entity = entity
        self._dbmodel = entity_model(entity)
        self._state = state
        self._tableModel = None
        self._data_initialized = False
        self._notifBar = NotificationBar(self.vlNotification)
        self._headers = []
        self._entity_attrs = []
        self._cell_formatters = {}
        self._searchable_columns = OrderedDict()

        #ID of a record to select once records have been added to the table
        self._select_item = None
        # Add maximize buttons
        self.setWindowFlags(self.windowFlags() |
                            Qt.WindowSystemMenuHint |
                            Qt.WindowMaximizeButtonHint)
        #Connect signals
        self.buttonBox.accepted.connect(self.onAccept)
        self.tbEntity.doubleClicked[QModelIndex].connect(self.onDoubleClickView)

    @property
    def entity(self):
        """
        :return: Returns the Entity object used in this browser.
        :rtype: Entity
        """
        return self._entity
        
    def setDatabaseModel(self,databaseModel):
        '''
        Set the database model that represents the entity for browsing its corresponding records.
        '''
        self._dbmodel = databaseModel
        
    def dateFormatter(self):
        """
        Function for formatting date values
        """
        return self._dateFormatter
    
    def setDateFormatter(self,formatter):
        """
        Sets the function for formatting date values. Overrides the default function. 
        """
        self._dateFormatter = formatter
          
    def state(self):
        '''
        Returns the current state that the dialog has been configured in.
        '''
        return self._state
    
    def setState(self,state):
        '''
        Set the state of the dialog.
        '''
        self._state = state

    def set_selection_record_id(self, id):
        """
        Set the ID of a record to be selected only once all records have been
        added to the table view.
        :param id: Record id to be selected.
        :type id: int
        """
        self._select_item = id
        
    def title(self):
        '''
        Set the title of the entity browser dialog.
        Protected method to be overridden by subclasses.
        '''
        records = QApplication.translate('EntityBrowser', 'Records')

        return u'{0} {1}'.format(self._entity.short_name, records)
    
    def setCellFormatters(self,formattermapping):
        '''
        Dictionary of attribute mappings and corresponding functions for 
        formatting the attribute value to the display value.
        '''
        self._cell_formatters = formattermapping
        
    def addCellFormatter(self,attributeName,formatterFunc):
        '''
        Add a new cell formatter configuration to the collection
        '''
        self._cell_formatters[attributeName] = formatterFunc
    
    def showEvent(self,showEvent):
        '''
        Override event for loading the database records once the dialog is visible.
        This is for improved user experience i.e. to prevent the dialog from taking
        long to load.
        '''
        self.setWindowTitle(self.title())
        
        if self._data_initialized:
            return
        try:
            if not self._dbmodel is None:
                self._initializeData()

        except Exception as ex:
            pass
            
        self._data_initialized = True
    
    def hideEvent(self,hideEvent):
        '''
        Override event which just sets a flag to indicate that the data records have already been
        initialized.
        '''
        pass
    
    def recomputeRecordCount(self):
        '''
        Get the number of records in the specified table and updates the window title.
        '''
        entity = self._dbmodel()
        
        #Get number of records
        numRecords = entity.queryObject().count()
        
        rowStr = "row" if numRecords == 1 else "rows"
        windowTitle = "{0} - {1} {2}".format(unicode(self.title()), \
                                                  unicode(QApplication.translate("EntityBrowser",
                                                                                 str(numRecords))),rowStr)
        self.setWindowTitle(windowTitle)
        
        return numRecords

    def _init_entity_columns(self):
        """
        Asserts if the entity columns actually do exist in the database. The
        method also initializes the table headers, entity column and cell
        formatters.
        """
        table_name = self._entity.name
        columns = table_column_names(table_name)
        missing_columns = []

        header_idx = 0

        #Iterate entity column and assert if they exist
        for c in self._entity.columns.values():
            #Do not include virtual columns in list of missing columns
            if not c.name in columns and not isinstance(c, VirtualColumn):
                missing_columns.append(c.name)

            else:
                header = c.header()
                self._headers.append(header)
                '''
                If it is a virtual column then use column name as the header
                but fully qualified column name (created by SQLAlchemy
                relationship) as the entity attribute name.
                '''
                col_name = c.name

                if isinstance(c, MultipleSelectColumn):
                    col_name = c.model_attribute_name

                self._entity_attrs.append(col_name)

                #Get widget factory so that we can use the value formatter
                w_factory = ColumnWidgetRegistry.factory(c.TYPE_INFO)
                if not w_factory is None:
                    formatter = w_factory(c)
                    self._cell_formatters[col_name] = formatter

                #Set searchable columns
                if c.searchable:
                    self._searchable_columns[header] = {
                        'name': c.name,
                        'header_index': header_idx
                    }

                header_idx += 1

        if len(missing_columns) > 0:
            msg = QApplication.translate(
                'EntityBrowser',
                u'The following columns have been defined in the '
                u'configuration but are missing in corresponding '
                u'database table, please re-run the configuration wizard '
                u'to create them.\n{0}'.format(
                    '\n'.join(missing_columns)
                )
            )

            QMessageBox.warning(
                self,
                QApplication.translate('EntityBrowser','Entity Browser'),
                msg
            )

    def _select_record(self, id):
        #Selects record with the given ID.
        if id is None:
            return

        m = self.tbEntity.model()
        s = self.tbEntity.selectionModel()

        start_idx = m.index(0, 0)
        idxs = m.match(
            start_idx,
            Qt.DisplayRole,
            id,
            1,
            Qt.MatchExactly
        )

        if len(idxs) > 0:
            sel_idx = idxs[0]
             #Select item
            s.select(
                sel_idx,
                QItemSelectionModel.ClearAndSelect|QItemSelectionModel.Rows
            )

    def _initializeData(self):
        '''
        Set table model and load data into it.
        '''
        if self._dbmodel is None:
            msg = QApplication.translate('EntityBrowser', 'The data model for '
                                                          'the entity could '
                                                          'not be loaded, '
                                                          'please contact '
                                                          'your database '
                                                          'administrator.')
            QMessageBox.critical(self, QApplication.translate('EntityBrowser',
                                                              'Entity Browser'),
                                 msg)

            return

        else:

            self._init_entity_columns()
            '''
            Load entity data. There might be a better way in future in order to ensure that
            there is a balance between user data discovery experience and performance.
            '''
            numRecords = self.recomputeRecordCount()
                        
            #Load progress dialog
            progressLabel = QApplication.translate("EntityBrowser", "Fetching Records...")
            progressDialog = QProgressDialog(progressLabel, None, 0, numRecords, self)
            
            entity_cls = self._dbmodel()
            entity_records = entity_cls.queryObject().filter().all()
            
            #Add records to nested list for enumeration in table model
            entity_records_collection = []
            for i,er in enumerate(entity_records):
                entity_row_info = []
                progressDialog.setValue(i)
                try:
                    for attr in self._entity_attrs:
                        attr_val = getattr(er, attr)

                        '''
                        Check if there are display formatters and apply if
                        one exists for the given attribute.
                        '''
                        if attr in self._cell_formatters:
                            formatter = self._cell_formatters[attr]
                            attr_val = formatter.format_column_value(attr_val)

                        entity_row_info.append(attr_val)

                except Exception as ex:
                    QMessageBox.critical(self,
                                         QApplication.translate(
                                             'EntityBrowser',
                                             'Loading Records'
                                         ),
                                         unicode(ex.message))
                    return

                entity_records_collection.append(entity_row_info)
                
            #Set maximum value of the progress dialog
            progressDialog.setValue(numRecords)

            headers = ','.join(self._headers)
            #QMessageBox.information(self, 'Info', headers)
        
            self._tableModel = BaseSTDMTableModel(entity_records_collection,
                                                  self._headers, self)

            #Add filter columns
            for header, info in self._searchable_columns.iteritems():
                column_name, index = info['name'], info['header_index']
                if column_name != 'id':
                    self.cboFilterColumn.addItem(header, info)
            
            #Use sortfilter proxy model for the view
            self._proxyModel = VerticalHeaderSortFilterProxyModel()
            self._proxyModel.setDynamicSortFilter(True)
            self._proxyModel.setSourceModel(self._tableModel)
            self._proxyModel.setSortCaseSensitivity(Qt.CaseInsensitive)

            #USe first column in the combo for filtering
            if self.cboFilterColumn.count() > 0:
                self.set_proxy_model_filter_column(0)
            
            self.tbEntity.setModel(self._proxyModel)
            self.tbEntity.setSortingEnabled(True)
            self.tbEntity.sortByColumn(1, Qt.AscendingOrder)
            
            #First (ID) column will always be hidden
            self.tbEntity.hideColumn(0)
            
            self.tbEntity.horizontalHeader().setResizeMode(QHeaderView.Interactive)

            self.tbEntity.resizeColumnsToContents()
            #Connect signals
            self.connect(self.cboFilterColumn, SIGNAL('currentIndexChanged (int)'), self.onFilterColumnChanged)
            self.connect(self.txtFilterPattern, SIGNAL('textChanged(const QString&)'), self.onFilterRegExpChanged)

            #Select record with the given ID if specified
            if not self._select_item is None:
                self._select_record(self._select_item)
            
    def _header_index_from_filter_combo_index(self, idx):
        col_info = self.cboFilterColumn.itemData(idx)

        return col_info['name'], col_info['header_index']

    def set_proxy_model_filter_column(self, index):
        #Set the filter column for the proxy model using the combo index
        name, header_idx = self._header_index_from_filter_combo_index(index)
        self._proxyModel.setFilterKeyColumn(header_idx)

    def onFilterColumnChanged(self, index):
        '''
        Set the filter column for the proxy model.
        '''
        self.set_proxy_model_filter_column(index)
        
    def onFilterRegExpChanged(self,text):
        '''
        Slot raised whenever the filter text changes.
        '''
        regExp =QRegExp(text,Qt.CaseInsensitive,QRegExp.FixedString)
        self._proxyModel.setFilterRegExp(regExp) 
        
    def onDoubleClickView(self,modelindex):
        '''
        Slot raised upon double clicking the table view.
        To be implemented by subclasses.
        '''
        pass
        
    def _selected_record_ids(self):
        '''
        Get the IDs of the selected row in the table view.
        '''
        self._notifBar.clear()
        
        selected_ids = []
        sel_row_indices = self.tbEntity.selectionModel().selectedRows(0)
        
        if len(sel_row_indices) == 0:
            msg = QApplication.translate("EntityBrowser", 
                                         "Please select a record from the table.")             
            self._notifBar.insertWarningNotification(msg)
            return selected_ids
        
        for proxyRowIndex in sel_row_indices:
            #Get the index of the source or else the row items will have unpredictable behavior
            row_index = self._proxyModel.mapToSource(proxyRowIndex)
            entity_id = row_index.data(Qt.DisplayRole)
            selected_ids.append(entity_id)
                
        return selected_ids
        
    def onAccept(self):
        '''
        Slot raised when user clicks to accept the dialog. The resulting action will be dependent 
        on the state that the browser is currently configured in.
        '''
        selIDs = self._selected_record_ids()
        if len(selIDs) == 0:
            return
        
        if self._mode == SELECT:
            #Get the first selected id
            selId = selIDs[0]
            self.recordSelected.emit(selId)

            self._notifBar.insertInformationNotification(
                QApplication.translate('EntityBrowser',
                                       'Record has been selected')
            )
            
    def addModelToView(self, model_obj):
        '''
        Convenience method for adding model info into the view.
        '''
        insertPosition = self._tableModel.rowCount()
        self._tableModel.insertRows(insertPosition, 1)

        for i, attr in enumerate(self._entity_attrs):
            prop_idx = self._tableModel.index(insertPosition, i)
            attr_val = getattr(model_obj, attr)

            '''
            Check if there are display formatters and apply if one exists
            for the given attribute.
            '''
            if attr in self._cell_formatters:
                formatter = self._cell_formatters[attr]
                attr_val = formatter.format_column_value(attr_val)

            self._tableModel.setData(prop_idx, attr_val)
            
    def _model_from_id(self, record_id):
        '''
        Convenience method that returns the model object based on its ID.
        '''
        dbHandler = self._dbmodel()
        modelObj = dbHandler.queryObject().filter(
            self._dbmodel.id == record_id
        ).first()
        
        return modelObj if not modelObj is None else None


class EntityBrowserWithEditor(EntityBrowser):
    """
    Entity browser with added functionality for carrying out CRUD operations
    directly.
    """
    def __init__(self,entity, parent=None, state=MANAGE):
        EntityBrowser.__init__(self, entity, parent, state)
        
        #Add action toolbar if the state contains Manage flag
        if (state & MANAGE) != 0:
            tbActions = QToolBar()
            tbActions.setObjectName('form_toolbar')
            tbActions.setIconSize(QSize(16, 16))
            tbActions.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            tbActions.setStyleSheet(
                '''
                    QToolButton {
                        border: 1px inset #777;
                        border-radius: 2px;
                        padding: 3px;
                        background-color: qlineargradient(
                            x1: 0, y1: 0, x2: 0, y2: 1,
                            stop: 0 #f6f7fa, stop: 1 #dadbde
                        );
                    }

                    QToolButton:pressed {
                        background-color: qlineargradient(
                            x1: 0, y1: 0, x2: 0, y2: 1,
                            stop: 0 #dadbde, stop: 1 #f6f7fa
                        );
                    }

                '''
            )
            self._newEntityAction = QAction(QIcon(":/plugins/stdm/images/icons/add.png"),
                                  QApplication.translate("EntityBrowserWithEditor", "Add"), self)

            self.connect(self._newEntityAction,SIGNAL("triggered()"),self.onNewEntity)
            
            self._editEntityAction = QAction(QIcon(":/plugins/stdm/images/icons/edit.png"),
                                  QApplication.translate("EntityBrowserWithEditor","Edit"),self)
            self.connect(self._editEntityAction,SIGNAL("triggered()"),self.onEditEntity)
        
            self._removeEntityAction = QAction(QIcon(":/plugins/stdm/images/icons/remove.png"),
                                  QApplication.translate("EntityBrowserWithEditor","Remove"),self)
            self.connect(self._removeEntityAction,SIGNAL("triggered()"),self.onRemoveEntity)
            
            tbActions.addAction(self._newEntityAction)
            tbActions.addAction(self._editEntityAction)
            tbActions.addAction(self._removeEntityAction)
            
            self.vlActions.addWidget(tbActions)
            
            self._editor_dlg = EntityEditorDialog


    def onNewEntity(self):
        '''
        Load editor dialog for adding a new record.
        '''
        addEntityDlg = self._editor_dlg(self._entity, parent=self)

        result = addEntityDlg.exec_()
        
        if result == QDialog.Accepted:
            model_obj = addEntityDlg.model()
            self.addModelToView(model_obj)
            self.recomputeRecordCount()
            
    def onEditEntity(self):
        '''
        Slot raised to load the editor for the selected row.
        '''
        self._notifBar.clear()
        
        selRowIndices = self.tbEntity.selectionModel().selectedRows(0)
        
        if len(selRowIndices) == 0:
            msg = QApplication.translate("EntityBrowserWithEditor", 
                                         "Please select a record in the table "
                                         "below for editing.")
            self._notifBar.insertWarningNotification(msg)

            return
        
        rowIndex = self._proxyModel.mapToSource(selRowIndices[0])
        recordid = rowIndex.data()
        self._load_editor_dialog(recordid, rowIndex.row())

    def onRemoveEntity(self):
        '''
        Load editor dialog for editing an existing record.
        '''
        self._notifBar.clear()
        
        selRowIndices = self.tbEntity.selectionModel().selectedRows(0)
        
        if len(selRowIndices) == 0:
            msg = QApplication.translate("EntityBrowserWithEditor", 
                                         "Please select a record in the table below to be deleted.")             
            self._notifBar.insertWarningNotification(msg)
            return
        
        rowIndex = self._proxyModel.mapToSource(selRowIndices[0])
        recordid = rowIndex.data()
        self._deleteRecord(recordid,rowIndex.row())
            
    def _load_editor_dialog(self, recid, rownumber):
        '''
        Load editor dialog based on the selected model instance with the given ID.
        '''
        model_obj = self._model_from_id(recid)

        #Load editor dialog
        edit_entity_dlg = self._editor_dlg(self._entity, model=model_obj,
                                         parent=self)
            
        result = edit_entity_dlg.exec_()
        
        if result == QDialog.Accepted:
            updated_model_obj = edit_entity_dlg.model()

            for i, attr in enumerate(self._entity_attrs):
                prop_idx = self._tableModel.index(rownumber, i)
                attr_val = getattr(updated_model_obj, attr)

                '''
                Check if there are display formatters and apply if
                one exists for the given attribute.
                '''
                if attr in self._cell_formatters:
                    formatter = self._cell_formatters[attr]
                    attr_val = formatter.format_column_value(attr_val)

                self._tableModel.setData(prop_idx, attr_val)
        
    def _deleteRecord(self, recid, rownumber):
        '''
        Delete the record with the given id and remove it from the table view.
        '''
        msg = QApplication.translate("EntityBrowserWithEditor",
                                             "Are you sure you want to delete the selected record?\nOnce deleted it cannot be recovered.")
        response = QMessageBox.warning(self,QApplication.translate("RespondentEntityBrowser","Delete Record"), msg,
                                    QMessageBox.Yes|QMessageBox.No, QMessageBox.No)
                
        if response == QMessageBox.Yes:
            
            self._tableModel.removeRows(rownumber,1) 
                                     
            #Remove record from the database
            dbHandler = self._dbmodel()
            entity = dbHandler.queryObject().filter(self._dbmodel.id == recid).first()
            
            if entity:
                entity.delete()

                #Clear previous notifications
                self._notifBar.clear()
                        
                #User notification
                delMsg = QApplication.translate("EntityBrowserWithEditor", 
                                         "Record has been successfully deleted!")
                self._notifBar.insertInformationNotification(delMsg)

    def onDoubleClickView(self, modelindex):
        '''
        Override for loading editor dialog.
        '''
        rowIndex = self._proxyModel.mapToSource(modelindex)
        rowNumber = rowIndex.row()
        recordIdIndex  = self._tableModel.index(rowNumber, 0)
    
        recordId = recordIdIndex.data()
        self._load_editor_dialog(recordId,recordIdIndex.row())
        
class ContentGroupEntityBrowser(EntityBrowserWithEditor):
    """
    Entity browser that loads editing tools based on the content permission
    settings defined by the administrator.
    This is an abstract class that needs to be implemented for subclasses
    representing specific entities.
    """
    def __init__(self,dataModel,tableContentGroup,parent = None,state = VIEW|MANAGE):
        EntityBrowserWithEditor.__init__(self, dataModel, parent, state)
        
        self.resize(700,500)
        
        if not isinstance(tableContentGroup,TableContentGroup):
            raise TypeError("Content group is not of type 'TableContentGroup'")
        
        self._tableContentGroup = tableContentGroup
        
        #Enable/disable tools based on permissions
        if (state & MANAGE) != 0:
            if not self._tableContentGroup.canCreate():
                self._newEntityAction.setVisible(False)
                    
            if not self._tableContentGroup.canUpdate():
                self._editEntityAction.setVisible(False)
                    
            if not self._tableContentGroup.canDelete():
                self._removeEntityAction.setVisible(False)
                
        self._setFormatters() 
        
    def _setFormatters(self):
        """
        Specify formatting mappings.
        Subclasses to implement.
        """   
        pass
    
    def onDoubleClickView(self, modelindex):
        """
        Checks if user has permission to edit.
        """
        if self._tableContentGroup.canUpdate():
            super(ContentGroupEntityBrowser,self).onDoubleClickView(modelindex)
    
    def tableContentGroup(self):
        """
        Returns the content group instance used in the browser.
        """
        return self._tableContentGroup

class ForeignKeyBrowser(EntityBrowser):
    """
    Browser for  foreign key records.
    """
    def __init__(self, parent=None, table=None, state=MANAGE):
        model = table

        if isinstance(table, str) or isinstance(table, unicode):
            mapping = DeclareMapping.instance()
            model = mapping.tableMapping(table)
            self._data_source_name = table

        else:
            self._data_source_name = table.__name__

        EntityBrowser.__init__(self, parent, model, state)

    def title(self):
        return QApplication.translate("EnumeratorEntityBrowser",
                    "%s Entity Records")%(self._data_source_name).replace("_"," ").capitalize()


    
    
        
        
    
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
    